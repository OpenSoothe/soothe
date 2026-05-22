"""Skill discovery helpers for built-in and user-installed skills."""

from __future__ import annotations

from pathlib import Path


def get_built_in_skills_paths(workspace: str | None = None) -> list[str]:
    """Return absolute paths for discovered skill directories.

    A valid skill directory contains a `SKILL.md` file. The search includes:
    - Package-bundled built-ins (`soothe/built_in_skills/`)
    - User skills in `~/.agents/skills/`
    - User skills in `~/.soothe/skills/`
    - Project skills in `<workspace>/.soothe/skills/` (if workspace provided)

    Args:
        workspace: Optional workspace directory path for project-local skills.

    Returns:
        Sorted absolute paths to skill directories.
    """
    module_dir = Path(__file__).resolve().parent.parent
    candidate_roots = [
        module_dir / "built_in_skills",
        Path.home() / ".agents" / "skills",
        Path.home() / ".soothe" / "skills",
    ]

    # Add workspace .soothe/skills if provided
    if workspace:
        ws_path = Path(workspace).expanduser().resolve()
        candidate_roots.append(ws_path / ".soothe" / "skills")

    discovered: list[str] = []
    seen: set[str] = set()
    for root in candidate_roots:
        if not root.exists() or not root.is_dir():
            continue

        for skill_file in root.glob("*/SKILL.md"):
            skill_dir = skill_file.parent.resolve()
            skill_path = str(skill_dir)
            if skill_path in seen:
                continue
            seen.add(skill_path)
            discovered.append(skill_path)

    return sorted(discovered)
