"""Skills loading utilities for the Soothe Textual TUI."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypedDict

import yaml

logger = logging.getLogger(__name__)


class ExtendedSkillMetadata(TypedDict, total=False):
    """Metadata for one discoverable skill directory (AgentSkills layout)."""

    name: str
    description: str
    path: str
    source: str
    version: str


def strip_skill_frontmatter(text: str) -> str:
    """Remove YAML frontmatter delimited by `---` markers from SKILL.md text.

    Args:
        text: Raw `SKILL.md` content.

    Returns:
        Body text with frontmatter removed and leading whitespace stripped.
    """
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return text
    end = stripped.find("\n---", 3)
    if end == -1:
        return text
    after = end + 4  # len("\n---")
    return stripped[after:].lstrip("\n")


def _split_yaml_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split leading YAML frontmatter from markdown body.

    Args:
        text: Raw file contents.

    Returns:
        Tuple of `(metadata dict, remainder text)`. On parse failure, metadata
        may be empty.
    """
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text
    end = stripped.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_raw = stripped[3:end].strip()
    body = stripped[end + 4 :].lstrip("\n")
    try:
        loaded = yaml.safe_load(fm_raw)
    except yaml.YAMLError:
        logger.debug("Invalid YAML frontmatter in SKILL.md", exc_info=True)
        return {}, body
    if not isinstance(loaded, dict):
        return {}, body
    return loaded, body


def _is_under_allowed_roots(target: Path, roots: Sequence[Path]) -> bool:
    """Return True if `target` is equal to or nested under one of `roots`."""
    t = target.resolve()
    for root in roots:
        try:
            t.relative_to(root.resolve())
        except ValueError:
            continue
        else:
            return True
    return False


def load_skill_content(skill_path: str | Path, *, allowed_roots: Sequence[Path] | None = None) -> str | None:
    """Read `SKILL.md` for a skill directory with optional path containment checks.

    Args:
        skill_path: Path to the skill directory **or** to a `SKILL.md` file.
        allowed_roots: Resolved directories that may contain the target file.
            When empty or ``None``, any resolved path is accepted (tests only —
            production callers should pass roots from `discover_skills_and_roots`).

    Returns:
        File contents as a string, or ``None`` only when the file is missing.

    Raises:
        PermissionError: When ``allowed_roots`` is non-empty and the resolved
            `SKILL.md` path lies outside every allowed root.
        OSError: Propagated from the filesystem when the file cannot be read.
    """
    raw = Path(skill_path)
    skill_md = raw / "SKILL.md" if raw.is_dir() else raw
    resolved_md = skill_md.resolve()

    if allowed_roots:
        roots = [Path(r).resolve() for r in allowed_roots]
        if roots and not _is_under_allowed_roots(resolved_md, roots):
            msg = f"Refusing to read skill file outside allowed directories: {resolved_md}"
            raise PermissionError(msg)

    if not resolved_md.is_file():
        return None

    return resolved_md.read_text(encoding="utf-8")


def parse_skill_directory(skill_dir: Path, *, source: str) -> ExtendedSkillMetadata | None:
    """Load metadata for one skill directory (must contain ``SKILL.md``).

    Args:
        skill_dir: Directory holding ``SKILL.md``.
        source: Provenance label (e.g. ``builtin``, ``user``, ``project``).

    Returns:
        Metadata dict, or ``None`` when the directory is not a valid skill.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Could not read SKILL.md at %s", skill_md, exc_info=True)
        return None

    meta, _ = _split_yaml_frontmatter(text)
    name_raw = meta.get("name")
    name = str(name_raw).strip().lower() if name_raw is not None else skill_dir.name.strip().lower()
    if not name:
        return None

    desc_val = meta.get("description", "")
    description = str(desc_val).strip() if desc_val is not None else ""

    out: ExtendedSkillMetadata = {
        "name": name,
        "description": description,
        "path": str(skill_dir.resolve()),
        "source": source,
    }
    ver_val = meta.get("version")
    if ver_val is not None and str(ver_val).strip():
        out["version"] = str(ver_val).strip()
    return out
