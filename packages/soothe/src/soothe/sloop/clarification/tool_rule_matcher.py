"""Pattern matching for tool-approval rules (RFC-622 §9b).

Adapts Claude Code's ``shellRuleMatching.ts`` command matching and
``filesystem.ts`` path matching to Python. Supports three command pattern
syntaxes (exact, prefix ``:*``, wildcard ``*``) and gitignore-style path
matching via ``pathspec``.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import pathspec

# ---------------------------------------------------------------------------
# Command pattern matching (adapted from shellRuleMatching.ts)
# ---------------------------------------------------------------------------

_WORKSPACE_TOKEN = "<workspace>"


def _parse_command_rule(pattern: str) -> dict[str, str]:
    """Parse a command permission pattern.

    Returns a dict with ``type`` (``"exact"``, ``"prefix"``, or
    ``"wildcard"``) and the relevant field (``command``, ``prefix``, or
    ``pattern``).

    Mirrors Claude Code's ``parsePermissionRule``.
    """
    # Legacy :* prefix syntax (e.g. "grep:*" → prefix "grep")
    if pattern.endswith(":*"):
        return {"type": "prefix", "prefix": pattern[:-2]}
    # Wildcard syntax (contains * but not :* at end)
    if _has_wildcards(pattern):
        return {"type": "wildcard", "pattern": pattern}
    # Exact match
    return {"type": "exact", "command": pattern}


def _has_wildcards(pattern: str) -> bool:
    """Check if a pattern contains unescaped wildcards.

    Mirrors Claude Code's ``hasWildcards``. A trailing ``:*`` is legacy
    prefix syntax, not a wildcard.
    """
    if pattern.endswith(":*"):
        return False
    # Check for unescaped *
    for i, ch in enumerate(pattern):
        if ch != "*":
            continue
        # Count preceding backslashes
        backslash_count = 0
        j = i - 1
        while j >= 0 and pattern[j] == "\\":
            backslash_count += 1
            j -= 1
        if backslash_count % 2 == 0:
            return True
    return False


def _match_wildcard(pattern: str, command: str, *, case_insensitive: bool = False) -> bool:
    """Match a command against a wildcard pattern.

    ``*`` matches any sequence of characters. ``\\*`` matches a literal
    asterisk. ``\\\\`` matches a literal backslash.

    Adapted from Claude Code's ``matchWildcardPattern``.
    """
    trimmed = pattern.strip()
    # Step 1: Process escape sequences into placeholders
    star_ph = "\x00STAR\x00"
    bs_ph = "\x00BS\x00"
    processed = ""
    i = 0
    while i < len(trimmed):
        ch = trimmed[i]
        if ch == "\\" and i + 1 < len(trimmed):
            nxt = trimmed[i + 1]
            if nxt == "*":
                processed += star_ph
                i += 2
                continue
            if nxt == "\\":
                processed += bs_ph
                i += 2
                continue
        processed += ch
        i += 1

    # Step 2: Escape regex special characters (except our placeholder markers)
    # Use a function replacement to avoid backreference interpretation
    escaped = re.sub(
        r"[.+?^${}()|[\]\\'\"]",
        lambda m: "\\" + m.group(),
        processed,
    )
    # Step 3: Convert unescaped * to .*
    with_wild = escaped.replace("*", ".*")
    # Step 4: Restore placeholders to escaped regex literals
    regex_str = with_wild.replace(star_ph, r"\*").replace(bs_ph, r"\\")

    # Trailing " *" with only one wildcard → make trailing optional
    # (aligns with prefix semantics, e.g. "git *" matches "git" and "git add")
    unescaped_star_count = processed.count("*")
    if regex_str.endswith(" .*") and unescaped_star_count == 1:
        regex_str = regex_str[:-3] + "( .*)?"

    flags = re.DOTALL | (re.IGNORECASE if case_insensitive else 0)
    return re.fullmatch(regex_str, command, flags) is not None


def match_command_rule(command: str, pattern: str) -> bool:
    """Match a shell command against a permission pattern.

    Supports three syntaxes (mirrors Claude Code's ``parsePermissionRule``):

    - ``"exact"`` — exact string match (e.g. ``"git status"``)
    - ``"prefix:*"`` — prefix match (e.g. ``"grep:*"`` matches ``"grep -r foo"``)
    - ``"wildcard*"`` — wildcard match (e.g. ``"pytest*"`` matches ``"pytest -xvs"``)

    Matching is case-insensitive for commands.
    """
    if not command or not pattern:
        return False

    rule = _parse_command_rule(pattern)
    cmd_lower = command.strip().lower()

    if rule["type"] == "exact":
        return cmd_lower == rule["command"].strip().lower()
    if rule["type"] == "prefix":
        prefix = rule["prefix"].strip().lower()
        return cmd_lower == prefix or cmd_lower.startswith(prefix + " ")
    if rule["type"] == "wildcard":
        return _match_wildcard(pattern, command.strip(), case_insensitive=True)
    return False


# ---------------------------------------------------------------------------
# Path pattern matching (adapted from filesystem.ts + pathspec)
# ---------------------------------------------------------------------------


def _expand_workspace(pattern: str, workspace_root: str | None) -> str | None:
    """Expand ``<workspace>`` token to the workspace root.

    Returns ``None`` if the pattern uses ``<workspace>`` but no workspace
    root is available (fail-safe: don't match).
    """
    if _WORKSPACE_TOKEN not in pattern:
        return pattern
    if not workspace_root:
        return None
    return pattern.replace(_WORKSPACE_TOKEN, workspace_root.rstrip("/"))


def match_path_rule(path: str, pattern: str, workspace_root: str | None) -> bool:
    """Match a file path against a permission pattern.

    Uses ``pathspec`` (gitignore-style) for ``**`` recursive matching.
    Expands the ``<workspace>`` token to ``workspace_root``.

    Supports:
    - ``<workspace>/**`` — any path inside workspace root
    - ``/etc/**`` — absolute path patterns
    - ``~/...`` — home directory patterns (expanded)
    - relative patterns resolved against workspace root

    Returns ``False`` if the pattern uses ``<workspace>`` but no workspace
    root is available (fail-safe).
    """
    if not path or not pattern:
        return False

    expanded = _expand_workspace(pattern, workspace_root)
    if expanded is None:
        return False

    # Normalize to POSIX paths
    path_posix = str(PurePosixPath(path))
    pattern_posix = str(PurePosixPath(expanded))

    # pathspec uses gitignore semantics: patterns without a leading / are
    # relative and match at any depth. Patterns with a leading / are
    # anchored to the root. We want anchored matching for absolute patterns.
    spec = pathspec.PathSpec.from_lines("gitignore", [pattern_posix])
    return spec.match_file(path_posix)


__all__ = [
    "match_command_rule",
    "match_path_rule",
]
