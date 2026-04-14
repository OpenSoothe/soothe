"""Skills invocation utilities for TUI (stub from deepagents-cli migration).

This module provides skill discovery and invocation envelope building functionality.
"""

from pathlib import Path

from soothe.ux.tui.skills.load import ExtendedSkillMetadata


def discover_skills_and_roots(assistant_id: str) -> tuple[list[ExtendedSkillMetadata], list[Path]]:
    """Discover available skills and resolve containment roots.

    Stub - returns empty lists.
    Full implementation should:
    1. Load skills from Soothe's built-in skills directory
    2. Load skills from user skills directory (~/.soothe/skills)
    3. Resolve containment roots for each skill
    4. Return (skill_metadata_list, containment_roots)

    Args:
        assistant_id: Assistant/agent identifier.

    Returns:
        Tuple of (skills list, containment roots list).
    """
    # Stub - return empty lists
    return [], []


def build_skill_invocation_envelope(
    skill_name: str,
    skill_content: str,
    user_message: str,
    containment_roots: list[Path] | None = None,
) -> dict:
    """Build skill invocation envelope for agent.

    Stub - returns minimal envelope.
    Full implementation should build proper envelope with:
    - Skill metadata
    - Skill content
    - User message context
    - Containment roots for file operations

    Args:
        skill_name: Name of skill to invoke.
        skill_content: Skill content from SKILL.md.
        user_message: User's prompt message.
        containment_roots: Optional list of allowed directories.

    Returns:
        Skill invocation envelope dictionary.
    """
    # Stub - return minimal envelope
    return {
        "skill_name": skill_name,
        "skill_content": skill_content,
        "user_message": user_message,
        "containment_roots": containment_roots or [],
    }
