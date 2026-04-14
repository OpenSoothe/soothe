"""Skills loading utilities for TUI (stub from deepagents-cli migration).

This module provides skill metadata and content loading functionality.
"""

from typing import Any


class ExtendedSkillMetadata:
    """Stub for extended skill metadata.

    Full implementation should integrate with Soothe skill metadata.
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        version: str = "1.0.0",
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.description = description
        self.version = version
        self.kwargs = kwargs


def load_skill_content(skill_path: str) -> str:
    """Load skill content from SKILL.md file.

    Stub - returns empty string.
    Full implementation should read SKILL.md file.

    Args:
        skill_path: Path to skill directory.

    Returns:
        Skill content string.
    """
    # Stub - return empty content
    return ""
