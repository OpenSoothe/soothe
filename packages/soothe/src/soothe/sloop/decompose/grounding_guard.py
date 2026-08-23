"""Grounding guard for decompose_task proposals (d15f hallucination defense).

Two runtime layers that reject decompose proposals issued without evidence:

- ``find_unconfirmed_paths``: a proposal whose subtasks cite files/dirs that
  do not exist in the workspace is rejected — the model must re-ground.
- ``current_evidence_calls`` (in :mod:`runtime`): a decompose_task issued
  with zero prior evidence-gathering tool calls in the thread is rejected.

Together they prevent the d15f failure: a complex root step called
``decompose_task`` as its first action (no grounding) and fabricated
``client/swift/``, ``client/kotlin/`` subtasks that did not exist.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from soothe.context.decomposition import DecompositionProposal

logger = logging.getLogger(__name__)

# Cap the number of cited paths checked per proposal, so a verbose proposal
# with many path-like tokens does not trigger an unbounded stat storm.
_MAX_PATHS_TO_CHECK = 20

# A path-like token: at least one ``/`` separating segments of word chars,
# dots, dashes. Filters out plain words and prose. ``client/swift/``,
# ``packages/client-go/src/goosews/``, ``src/foo.py`` all match; ``Swift``,
# ``Go``, ``do the work`` do not.
_PATH_TOKEN_RE = re.compile(r"(?<![\w./-])[\w][\w./-]*\/[\w./-]+")

# Common English words that the regex might capture when they contain a
# slash from a contraction or heading like "add/delete" — drop these.
_PROSE_DENYLIST = frozenset(
    {
        "add/delete",
        "create/replace",
        "read/write",
        "input/output",
        "source/destination",
        "before/after",
        "and/or",
    }
)


def _looks_like_path(token: str) -> bool:
    """Heuristic: does this token look like a deliberate file/dir reference?

    Conservative — when in doubt return False so the guard does not block
    legitimate prose. A token is path-like when it has a path separator AND
    either ends with ``/`` (dir), has a file extension (``.py``/``.go``),
    or has 2+ segments where one looks like a code identifier.
    """
    if not token or "/" not in token:
        return False
    if token.lower() in _PROSE_DENYLIST:
        return False
    stripped = token.strip("/.")
    if not stripped:
        return False
    # Drop tokens that are really two English words joined by a slash
    # (e.g. "enhance/test", "review/polish") unless one segment has a dot
    # (extension) or the token ends with ``/`` (explicit dir).
    if token.endswith("/"):
        return True
    if "." in stripped.split("/")[-1]:  # last segment has a file extension
        return True
    return False


def extract_cited_paths(text: str) -> list[str]:
    """Extract candidate relative file/dir paths from ``text``.

    Returns deduplicated paths (preserving first-seen order). Conservative:
    only tokens that pass :func:`_looks_like_path` are returned.
    """
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _PATH_TOKEN_RE.finditer(text):
        token = match.group(0).strip(".,;:()[]\"'`")
        if _looks_like_path(token) and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _collect_proposal_paths(proposal: DecompositionProposal) -> list[str]:
    """Gather all cited paths across the proposal's subtasks (deduped)."""
    seen: set[str] = set()
    out: list[str] = []
    for sub in proposal.subtasks:
        for field in (sub.description, sub.full_description, sub.expected_output):
            for path in extract_cited_paths(field or ""):
                if path not in seen:
                    seen.add(path)
                    out.append(path)
    return out


def find_unconfirmed_paths(
    proposal: DecompositionProposal,
    *,
    workspace: str | None,
) -> list[str]:
    """Return cited paths in ``proposal`` that do not exist in ``workspace``.

    Resolves each cited path against the workspace root. A path is confirmed
    when it exists as a file, directory, or any filesystem entry. Returns only
    the missing paths.

    Fails open when no workspace is available (``None`` or empty): the guard
    cannot reliably resolve paths without a workspace root, so it returns no
    missing paths rather than risk blocking legitimate work on a misresolved
    cwd. The evidence-call gate (scheme 2d) still applies.

    Conservative: caps at :data:`_MAX_PATHS_TO_CHECK` cited paths; when in
    doubt about whether a token is a real path, it is not checked (fail
    open — never block legitimate work on a misread).
    """
    if not workspace:
        return []
    cited = _collect_proposal_paths(proposal)
    if not cited:
        return []
    base = Path(workspace).expanduser()
    missing: list[str] = []
    for path_str in cited[:_MAX_PATHS_TO_CHECK]:
        candidate = Path(path_str)
        resolved = candidate if candidate.is_absolute() else (base / candidate)
        try:
            if not resolved.exists():
                missing.append(path_str)
        except OSError:
            # Filesystem error — treat as confirmed (fail open).
            continue
    return missing


def build_unconfirmed_paths_guidance(
    missing: list[str],
    *,
    step_id: str,
) -> str:
    """Build the soft-rejection guidance returned to the LLM for unconfirmed paths."""
    preview = ", ".join(missing[:5])
    return (
        f"Decomposition proposal for step {step_id} was NOT queued: it cites "
        f"areas that could not be confirmed to exist ({preview}"
        f"{', …' if len(missing) > 5 else ''}). Gather evidence first — run "
        f"ls/glob/grep to confirm which of these areas exist, then re-propose "
        f"only the confirmed ones. Do not fabricate subtasks for paths you "
        f"have not verified."
    )


def build_no_evidence_guidance(*, step_id: str) -> str:
    """Build the soft-rejection guidance returned to the LLM when no evidence was gathered."""
    return (
        f"Decomposition proposal for step {step_id} was NOT queued: no "
        f"evidence-gathering tool (ls/glob/grep/read_file) has run in this "
        f"thread yet. Gather evidence first — run at least one search or "
        f"inspection to confirm the areas this task spans, then call "
        f"decompose_task. Decomposing without evidence produces fabricated "
        f"subtasks."
    )


__all__ = [
    "build_no_evidence_guidance",
    "build_unconfirmed_paths_guidance",
    "extract_cited_paths",
    "find_unconfirmed_paths",
]
