"""Skills catalog: discovery, resolution, and invocation for the Soothe daemon."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from soothe.config import SootheConfig
from soothe.skills.builtins import get_built_in_skills_paths

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# YAML-like frontmatter parser (lightweight, no yaml dependency required)
# ---------------------------------------------------------------------------

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_FM_LINE_RE = re.compile(r"^(\w[\w_-]*):\s*(.+)$")


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse YAML-like frontmatter from SKILL.md content.

    Args:
        text: Full SKILL.md content, possibly with ``---`` delimited header.

    Returns:
        Dict of parsed key-value pairs (strings only; no list/tag parsing).
    """
    m = _FM_RE.match(text)
    if not m:
        return {}

    result: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        lm = _FM_LINE_RE.match(line.strip())
        if lm:
            key, val = lm.group(1), lm.group(2).strip()
            # Strip surrounding quotes
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            result[key] = val
    return result


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
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def wire_entries_for_agent_config(config: SootheConfig) -> list[dict[str, str]]:
    """Return wire-safe skill metadata sorted by name.

    Scans built-in, user, and project skill directories declared in the
    config and returns a list of dicts suitable for RPC serialization.
    The ``path`` field is intentionally excluded (wire-safe).

    Args:
        config: SootheConfig with optional ``config.skills`` directories.

    Returns:
        List of ``{name, description, source, version?}`` dicts sorted
        alphabetically by name. No ``path`` field is included.
    """
    all_dirs: list[str] = list(get_built_in_skills_paths())
    if config.skills:
        all_dirs.extend(config.skills)

    entries: list[dict[str, str]] = []
    seen_names: set[str] = set()

    for dir_path in all_dirs:
        meta = _parse_skill_directory(dir_path)
        if meta is None:
            continue

        # Determine source label
        builtin_dirs = get_built_in_skills_paths()
        if dir_path in builtin_dirs or "built_in_skills" in dir_path:
            source = "builtin"
        else:
            source = "user"

        entry: dict[str, str] = {
            "name": meta["name"],
            "description": meta["description"],
            "source": source,
        }
        if meta.get("version"):
            entry["version"] = meta["version"]

        # Last-wins: later entries override earlier ones with same name
        if meta["name"] in seen_names:
            entries = [e for e in entries if e["name"] != meta["name"]]
        seen_names.add(meta["name"])
        entries.append(entry)

    entries.sort(key=lambda e: e["name"].lower())
    return entries


def resolve_skill_directory(
    config: SootheConfig,
    skill_name: str,
) -> dict[str, Any] | None:
    """Resolve skill name to metadata with path (last-wins precedence).

    Searches skill directories in order: built-in first, then user/project
    directories from config. The last matching entry wins, allowing user
    overrides of built-in skills.

    Args:
        config: SootheConfig with optional ``config.skills`` directories.
        skill_name: Skill name to resolve.

    Returns:
        Metadata dict with ``path`` field for daemon-side file access,
        or ``None`` if the skill is not found.
    """
    all_dirs: list[str] = list(get_built_in_skills_paths())
    if config.skills:
        all_dirs.extend(config.skills)

    # Last-wins: iterate all, keep last match
    result: dict[str, Any] | None = None
    for dir_path in all_dirs:
        meta = _parse_skill_directory(dir_path)
        if meta is None:
            continue
        if meta["name"] == skill_name:
            # Determine source label
            builtin_dirs = get_built_in_skills_paths()
            if dir_path in builtin_dirs or "built_in_skills" in dir_path:
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


@dataclass
class SkillInvocationEnvelope:
    """Envelope for a skill invocation turn queued to the agent.

    Attributes:
        prompt: Composed skill invocation prompt sent as agent input.
        message_kwargs: Additional kwargs with ``soothe_skill`` marker.
    """

    prompt: str
    message_kwargs: dict[str, Any] = field(default_factory=dict)


def build_skill_invocation_envelope(
    meta: dict[str, Any],
    markdown: str,
    args: str | None = None,
) -> SkillInvocationEnvelope:
    """Compose skill invocation envelope for agent turn.

    Args:
        meta: Skill metadata dict (``name``, ``description``, etc.).
        markdown: Full SKILL.md content (frontmatter + body).
        args: Optional user arguments appended to the prompt.

    Returns:
        ``SkillInvocationEnvelope`` with composed prompt and message kwargs.
    """
    body = _strip_frontmatter(markdown)
    name = meta.get("name", "")
    description = meta.get("description", "")

    parts: list[str] = []
    if name:
        parts.append(f"Skill: {name}")
    if description:
        parts.append(f"Description: {description}")
    if body.strip():
        parts.append(body.strip())
    if args:
        parts.append(f"Arguments: {args}")

    prompt = "\n\n".join(parts)

    message_kwargs = {
        "additional_kwargs": {
            "soothe_skill": name,
        },
    }

    return SkillInvocationEnvelope(prompt=prompt, message_kwargs=message_kwargs)
