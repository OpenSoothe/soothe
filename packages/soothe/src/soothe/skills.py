"""Skill discovery helpers for built-in and user-installed skills."""

from __future__ import annotations

from pathlib import Path


def get_built_in_skills_paths() -> list[str]:
    """Return absolute paths for discovered skill directories.

    A valid skill directory contains a `SKILL.md` file. The search includes
    package-bundled built-ins and common local skill installation directories.

    Returns:
        Sorted absolute paths to skill directories.
    """
    module_dir = Path(__file__).resolve().parent
    candidate_roots = [
        module_dir / "built_in_skills",
        Path.home() / ".cursor" / "skills-cursor",
        Path.home() / ".cursor" / "skills",
        Path.home() / ".claude" / "skills",
        Path.home() / ".agents" / "skills",
        Path.home() / ".qoder" / "skills",
    ]

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
