"""Skills catalog: discovery, resolution, and invocation for Soothe."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_nano.config import SootheConfig
from soothe_nano.skills.builtins import is_builtin_skill_directory
from soothe_nano.skills.workspace_sync import skill_directories_for_resolution

if TYPE_CHECKING:
    from soothe_nano.skills.index import SkillIndex

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# YAML-like frontmatter parser (lightweight, no yaml dependency required)
# ---------------------------------------------------------------------------

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_FM_LINE_RE = re.compile(r"^(\w[\w_-]*):\s*(.+)$")


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse YAML-like frontmatter from SKILL.md content.

    Supports scalar keys, block-list ``paths:`` entries (``- pattern``), and
    block-scalar ``when_to_use: |`` multi-line values (RFC-105).

    Args:
        text: Full SKILL.md content, possibly with ``---`` delimited header.

    Returns:
        Dict of parsed key-value pairs.
    """
    m = _FM_RE.match(text)
    if not m:
        return {}

    result: dict[str, Any] = {}
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Block-list: "key:" followed by indented "  - item" lines
        if stripped.endswith(":") and i + 1 < len(lines) and _is_list_line(lines[i + 1]):
            key = stripped[:-1].strip()
            items: list[str] = []
            j = i + 1
            while j < len(lines) and _is_list_line(lines[j]):
                item = lines[j].strip().lstrip("-").strip()
                if (item.startswith('"') and item.endswith('"')) or (
                    item.startswith("'") and item.endswith("'")
                ):
                    item = item[1:-1]
                items.append(item)
                j += 1
            result[key] = items
            i = j
            continue

        # Block-scalar: "key: |" or "key: >" followed by indented lines
        lm = _FM_LINE_RE.match(stripped)
        if lm and lm.group(2).strip() in ("|", ">"):
            key = lm.group(1)
            block_lines: list[str] = []
            j = i + 1
            while j < len(lines) and (lines[j].startswith(("  ", "\t")) or not lines[j].strip()):
                if not lines[j].strip():
                    block_lines.append("")
                else:
                    block_lines.append(
                        lines[j][2:] if lines[j].startswith("  ") else lines[j].lstrip()
                    )
                j += 1
            result[key] = "\n".join(block_lines).rstrip()
            i = j
            continue

        # Scalar key: value
        if lm:
            key, val = lm.group(1), lm.group(2).strip()
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            result[key] = val

        i += 1
    return result


def _is_list_line(line: str) -> bool:
    """Check if a line is a YAML list item (indented, starts with '-')."""
    stripped = line.strip()
    return stripped.startswith("- ") and (line.startswith("  ") or line.startswith("\t"))


def _strip_frontmatter(text: str) -> str:
    """Remove frontmatter block, returning only the body content.

    Args:
        text: Full SKILL.md content.

    Returns:
        Body content after frontmatter, or the original text if no frontmatter.
    """
    m = _FM_RE.match(text)
    if m:
        return text[m.end() :]
    return text


def _parse_skill_directory(skill_dir: str | Path) -> dict[str, Any] | None:
    """Parse a skill directory's SKILL.md and return metadata with path.

    Args:
        skill_dir: Path to the skill directory (must contain SKILL.md).

    Returns:
        Metadata dict with ``name``, ``description``, ``path``, and optional
        fields, or ``None`` if the directory is invalid.
    """
    skill_path = Path(skill_dir)
    md_file = skill_path / "SKILL.md"
    if not md_file.exists():
        return None

    try:
        text = md_file.read_text(encoding="utf-8")
    except OSError:
        logger.debug("Failed to read SKILL.md in %s", skill_dir)
        return None

    fm = _parse_frontmatter(text)
    body = _strip_frontmatter(text)

    # Derive name from frontmatter or directory name
    name = fm.get("name", skill_path.name)
    # Derive description from frontmatter or first heading/line of body
    description = fm.get("description", "")
    if not description:
        # Try first markdown heading or first non-empty line
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                description = stripped.lstrip("#").strip()
                break
            if stripped:
                description = stripped
                break

    return {
        "name": name,
        "description": description,
        "path": str(skill_path.resolve()),
        "source": fm.get("source", ""),
        "version": fm.get("version", ""),
        "tags": fm.get("tags", ""),
        "tools": fm.get("tools", None),
        "default_model": fm.get("default_model", None),
        "requires": fm.get("requires", None),
        "paths": fm.get("paths", None),
        "when_to_use": fm.get("when_to_use", None),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def wire_entries_for_agent_config(
    config: SootheConfig,
    workspace: str | None = None,
    *,
    skill_index: SkillIndex | None = None,
    mcp_registry: Any | None = None,
) -> list[dict[str, str]]:
    """Return wire-safe skill metadata sorted by name.

    When ``skill_index`` is provided, global user skills are served from the
    cached index (fast, stat-only invalidation) and only workspace-local skills
    are scanned from the filesystem. Without an index, falls back to full
    filesystem scan for backward compatibility.

    Args:
        config: SootheConfig with optional ``config.skills`` directories.
        workspace: Optional workspace directory for project-local skills
            (scans `<workspace>/.soothe/skills/`). Falls back to cwd if not provided.
        skill_index: Optional ``SkillIndex`` instance for incremental loading.
        mcp_registry: Optional ``MCPRegistry`` to include MCP server prompts.

    Returns:
        List of ``{name, description, source, version?}`` dicts sorted
        alphabetically by name. No ``path`` field is included.
    """
    if skill_index is not None:
        entries = _wire_entries_from_index(config, workspace, skill_index)
    else:
        entries = _wire_entries_full_scan(config, workspace)

    if mcp_registry is not None:
        _merge_mcp_prompt_entries(entries, mcp_registry)

    return entries


def _wire_entries_from_index(
    config: SootheConfig,
    workspace: str | None,
    skill_index: SkillIndex,
) -> list[dict[str, str]]:
    """Build wire entries using cached index for global skills + filesystem for workspace."""
    entries: list[dict[str, str]] = []
    seen_names: set[str] = set()

    # Global user skills from index (fast path)
    for idx_entry in skill_index.rebuild_if_stale():
        entry: dict[str, Any] = {
            "name": idx_entry.name,
            "description": idx_entry.description,
            "source": idx_entry.source,
        }
        if idx_entry.tags:
            entry["tags"] = idx_entry.tags
        if idx_entry.paths is not None:
            entry["paths"] = list(idx_entry.paths)
        if idx_entry.when_to_use is not None:
            entry["when_to_use"] = idx_entry.when_to_use
        seen_names.add(idx_entry.name)
        entries.append(entry)

    # Workspace-local skills (filesystem scan, small set)
    ws = workspace or str(Path.cwd().resolve())
    from soothe_nano.skills.workspace_sync import workspace_skills_mirror_root

    mirror = workspace_skills_mirror_root(ws)
    if mirror.is_dir():
        for skill_md in mirror.glob("*/SKILL.md"):
            meta = _parse_skill_directory(str(skill_md.parent.resolve()))
            if meta is None:
                continue
            name = meta["name"]
            # Workspace wins over global (last-wins)
            if name in seen_names:
                entries = [e for e in entries if e["name"] != name]
            seen_names.add(name)
            entry = {
                "name": name,
                "description": meta["description"],
                "source": "project",
            }
            if meta.get("version"):
                entry["version"] = meta["version"]
            if meta.get("paths"):
                entry["paths"] = meta["paths"]
            if meta.get("when_to_use"):
                entry["when_to_use"] = meta["when_to_use"]
            entries.append(entry)

    entries.sort(key=lambda e: e["name"].lower())
    return entries


def _wire_entries_full_scan(
    config: SootheConfig,
    workspace: str | None,
) -> list[dict[str, str]]:
    """Legacy full-scan path (no index available)."""
    ws = workspace or str(Path.cwd().resolve())
    all_dirs = skill_directories_for_resolution(config, ws)

    entries: list[dict[str, str]] = []
    seen_names: set[str] = set()

    for dir_path in all_dirs:
        meta = _parse_skill_directory(dir_path)
        if meta is None:
            continue

        if is_builtin_skill_directory(dir_path):
            source = "builtin"
        else:
            source = "user"

        entry: dict[str, Any] = {
            "name": meta["name"],
            "description": meta["description"],
            "source": source,
        }
        if meta.get("version"):
            entry["version"] = meta["version"]
        if meta.get("paths"):
            entry["paths"] = meta["paths"]
        if meta.get("when_to_use"):
            entry["when_to_use"] = meta["when_to_use"]

        if meta["name"] in seen_names:
            entries = [e for e in entries if e["name"] != meta["name"]]
        seen_names.add(meta["name"])
        entries.append(entry)

    entries.sort(key=lambda e: e["name"].lower())
    return entries


def _merge_mcp_prompt_entries(
    entries: list[dict[str, Any]],
    mcp_registry: Any,
) -> None:
    """Append MCP server prompt descriptors into skill wire entries in-place."""
    try:
        server_prompts = mcp_registry.prompts()
    except Exception:  # noqa: BLE001
        return
    seen = {e["name"] for e in entries}
    for server_name, prompts in server_prompts.items():
        for p in prompts:
            name = p.get("name", "")
            if not name or name in seen:
                continue
            entry: dict[str, Any] = {
                "name": name,
                "description": p.get("description") or f"MCP prompt from {server_name}",
                "source": f"mcp:{server_name}",
            }
            seen.add(name)
            entries.append(entry)
    entries.sort(key=lambda e: e["name"].lower())


def resolve_skill_directory(
    config: SootheConfig,
    skill_name: str,
    workspace: str | None = None,
) -> dict[str, Any] | None:
    """Resolve skill name to metadata with path (last-wins precedence).

    Searches skill directories in order: built-in first, then user/project
    directories from config. The last matching entry wins, allowing user
    overrides of built-in skills.

    Args:
        config: SootheConfig with optional ``config.skills`` directories.
        skill_name: Skill name to resolve.
        workspace: Optional workspace directory for project-local skills.
            Falls back to cwd if not provided.

    Returns:
        Metadata dict with ``path`` field for daemon-side file access,
        or ``None`` if the skill is not found.
    """
    ws = workspace or str(Path.cwd().resolve())
    all_dirs = skill_directories_for_resolution(config, ws)

    # Last-wins: iterate all, keep last match
    result: dict[str, Any] | None = None
    for dir_path in all_dirs:
        meta = _parse_skill_directory(dir_path)
        if meta is None:
            continue
        if meta["name"] == skill_name:
            # Determine source label
            if is_builtin_skill_directory(dir_path):
                meta["source"] = "builtin"
            else:
                meta["source"] = "user"
            result = meta

    return result


def read_skill_markdown(meta: dict[str, Any]) -> str | None:
    """Read SKILL.md content from resolved metadata.

    Args:
        meta: Metadata dict with ``path`` field from ``resolve_skill_directory()``.

    Returns:
        Full SKILL.md content (frontmatter + body), or ``None`` if read fails.
    """
    path_str = meta.get("path")
    if not path_str:
        return None

    md_file = Path(path_str) / "SKILL.md"
    try:
        return md_file.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Failed to read SKILL.md at %s", md_file)
        return None


def build_skill_context_text(meta: dict[str, Any], markdown: str) -> str:
    """Compose skill reference text (name, folder path, description, SKILL.md body).

    Used for execute-step ``<SKILL_CONTEXT>`` blocks; excludes the short user instruction
    prefix that ``build_skill_invocation_envelope`` places ahead of the reference.

    Args:
        meta: Skill metadata dict (``name``, ``description``, ``path``, etc.).
        markdown: Full SKILL.md content (frontmatter + body).

    Returns:
        Skill reference body for ``<SKILL_CONTEXT>``.
    """
    body = _strip_frontmatter(markdown)
    name = meta.get("name", "")
    description = meta.get("description", "")
    skill_dir = str(meta.get("path") or "").strip()
    source = str(meta.get("source") or "").strip().lower()

    reference_parts: list[str] = []
    if name:
        reference_parts.append(f"Skill: {name}")
    if skill_dir and source != "builtin" and not is_builtin_skill_directory(skill_dir):
        reference_parts.append(
            f"Skill folder: {skill_dir}\n"
            "(Additional files may live under this directory — use filesystem tools to "
            "read them when SKILL.md is not sufficient.)"
        )
    if description:
        reference_parts.append(f"Description: {description}")
    if body.strip():
        reference_parts.append(body.strip())
    return "\n\n".join(reference_parts)


@dataclass
class SkillInvocationEnvelope:
    """Envelope for a skill invocation turn queued to the agent.

    Attributes:
        prompt: Composed skill invocation prompt sent as agent input.
        skill_context: Skill reference only (for execute-step ``<SKILL_CONTEXT>``).
        message_kwargs: Additional kwargs with ``soothe_skill`` marker.
    """

    prompt: str
    skill_context: str
    message_kwargs: dict[str, Any] = field(default_factory=dict)


def format_slash_skill_invoke_line(skill_name: str, args: str | None = None) -> str:
    """Build the canonical user query line for a skill turn (no SKILL.md body).

    Daemon and TUI submit this plain string as loop input; the runner expands it
    into the full skill envelope before the model sees the turn.

    Args:
        skill_name: Resolved skill name (e.g. frontmatter ``name``).
        args: Optional user text after the skill selector.

    Returns:
        ``/skill:<name>`` or ``/skill:<name> <args>`` with a single space before args.

    Raises:
        ValueError: If ``skill_name`` is empty after stripping.
    """
    name = str(skill_name or "").strip()
    if not name:
        msg = "skill_name is required for format_slash_skill_invoke_line"
        raise ValueError(msg)
    tail = str(args or "").strip()
    if tail:
        return f"/skill:{name} {tail}"
    return f"/skill:{name}"


def parse_slash_skill_user_line(text: str) -> tuple[str, str] | None:
    """Parse a user line that selects a skill via ``/skill:<name>``.

    The prefix match is case-insensitive. The skill token is normalized to
    lowercase so it matches wire/catalog names consistently with the CLI TUI.

    Args:
        text: Full user input (typically one logical line).

    Returns:
        ``(skill_name_lower, trailing_args)`` when the trimmed text begins with
        ``/skill:`` and a non-empty name follows; otherwise ``None``.
    """
    s = text.strip()
    if len(s) < len("/skill:") + 1:
        return None
    if s[: len("/skill:")].lower() != "/skill:":
        return None
    rest = s[len("/skill:") :].strip()
    if not rest:
        return None
    parts = rest.split(maxsplit=1)
    if not parts[0]:
        return None
    skill_token = parts[0].lower()
    tail = parts[1] if len(parts) > 1 else ""
    return (skill_token, tail)


def build_skill_invocation_envelope(
    meta: dict[str, Any],
    markdown: str,
    args: str | None = None,
) -> SkillInvocationEnvelope:
    """Compose skill invocation envelope for agent turn.

    Args:
        meta: Skill metadata dict (``name``, ``description``, etc.).
        markdown: Full SKILL.md content (frontmatter + body).
        args: Optional trailing user text after ``/skill:``; placed first in the composed
            prompt so short instructions are not buried after SKILL.md content.

    Returns:
        ``SkillInvocationEnvelope`` with composed prompt and message kwargs.
    """
    reference_text = build_skill_context_text(meta, markdown)
    name = meta.get("name", "")

    user_instruction = (args or "").strip()
    composed: list[str] = []
    if user_instruction:
        composed.append(
            "User instruction (short — prioritize this over long skill reference text):\n"
            f"{user_instruction}"
        )
    if reference_text:
        composed.append(
            "Skill reference (instructions, constraints, workflow — use to carry out "
            "the user instruction):\n" + reference_text
        )
    prompt = "\n\n".join(composed) if composed else reference_text

    message_kwargs = {
        "additional_kwargs": {
            "soothe_skill": name,
        },
    }

    return SkillInvocationEnvelope(
        prompt=prompt,
        skill_context=reference_text,
        message_kwargs=message_kwargs,
    )


def try_expand_slash_skill_user_line(
    text: str,
    config: SootheConfig,
    workspace: str | None = None,
) -> SkillInvocationEnvelope | None:
    """If ``text`` is a ``/skill:`` line, resolve the skill and build the model envelope.

    When resolution fails (unknown skill, unreadable SKILL.md), returns ``None``
    so callers can fall back to treating ``text`` as a normal user message.

    Args:
        text: Raw user input.
        config: Active ``SootheConfig`` for skill path resolution.
        workspace: Optional workspace directory for project-local skills.

    Returns:
        A populated ``SkillInvocationEnvelope``, or ``None`` when not a slash-skill
        line or when the skill cannot be loaded.
    """
    parsed = parse_slash_skill_user_line(text)
    if parsed is None:
        return None
    skill_name, args = parsed
    meta = resolve_skill_directory(config, skill_name, workspace)
    if meta is None:
        return None
    md = read_skill_markdown(meta)
    if md is None or not str(md).strip():
        return None
    return build_skill_invocation_envelope(meta, md, args)
