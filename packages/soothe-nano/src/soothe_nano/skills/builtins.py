"""Skill discovery helpers for built-in and user-installed skills."""

from __future__ import annotations

from pathlib import Path

from soothe_nano.config import SOOTHE_HOME

_BUILTIN_SKILLS_DIR_NAME = "builtin_skills"


def is_builtin_skill_directory(skill_dir: str | Path) -> bool:
    """Return True for package-bundled skills under ``soothe_nano/skills/builtin_skills/``."""
    resolved = Path(skill_dir).expanduser().resolve()
    package_builtins = Path(__file__).resolve().parent / _BUILTIN_SKILLS_DIR_NAME
    try:
        if resolved.is_relative_to(package_builtins.resolve()):
            return True
    except (ValueError, OSError):
        pass
    return _BUILTIN_SKILLS_DIR_NAME in resolved.parts


def get_built_in_skills_paths(workspace: str | None = None) -> list[str]:
    """Return absolute paths for discovered skill directories.

    A valid skill directory contains a `SKILL.md` file. The search includes:
    - User skills in `~/.agents/skills/`
    - Package-bundled built-ins (`soothe_nano/skills/builtin_skills/`)
    - User skills in `~/.soothe/skills/`
    - Project skills in `<workspace>/.soothe/skills/` (if workspace provided)

    When the same skill name exists in multiple roots, later roots win
    (last-wins dedup). Workspace overrides ``~/.soothe`` which overrides
    built-ins which override ``~/.agents``.

    Args:
        workspace: Optional workspace directory path for project-local skills.

    Returns:
        Sorted absolute paths to skill directories.
    """
    skills_dir = Path(__file__).resolve().parent
    candidate_roots = [
        Path.home() / ".agents" / "skills",
        skills_dir / "builtin_skills",
        SOOTHE_HOME / "skills",
    ]

    # Add workspace .soothe/skills if provided
    if workspace:
        ws_path = Path(workspace).expanduser().resolve()
        candidate_roots.append(ws_path / ".soothe" / "skills")

    # Last-wins dedup by skill directory name (case-insensitive)
    by_name: dict[str, str] = {}
    for root in candidate_roots:
        if not root.exists() or not root.is_dir():
            continue

        for skill_file in root.glob("*/SKILL.md"):
            skill_dir = skill_file.parent.resolve()
            skill_path = str(skill_dir)
            by_name[skill_dir.name.lower()] = skill_path

    return sorted(by_name.values())
