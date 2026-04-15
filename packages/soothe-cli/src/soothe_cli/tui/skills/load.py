"""Skills loading utilities for the Soothe Textual TUI."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)


class ExtendedSkillMetadata(TypedDict):
    """Wire-safe skill metadata from daemon RPC (IG-174 Phase 2).

    This TypedDict represents skill metadata fetched from daemon via WebSocket RPC.
    All fields are wire-safe (no Path objects, use str representations).
    """
    name: str
    description: str
    source: str  # "builtin", "user", "project", "agents", "claude"
    path: str | None  # Wire-safe path representation (not Path object)
    tags: list[str]
    tools: list[str] | None
    default_model: str | None
    requires: list[str] | None


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


def load_skill_content(
    skill_path: str | Path, *, allowed_roots: Sequence[Path] | None = None
) -> str | None:
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


# Re-export for callers that import from this module
__all__ = [
    "ExtendedSkillMetadata",
    "load_skill_content",
]
