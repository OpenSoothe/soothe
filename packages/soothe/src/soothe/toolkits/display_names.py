"""Tool display names for user-facing messages.

Automatically converts internal tool names (snake_case) to user-facing
display names (PascalCase) for consistent presentation in CLI and TUI interfaces.

This module provides a single function: get_tool_display_name()

Pattern: Programmatic conversion - no manual registration needed.
"""

from __future__ import annotations


def get_tool_display_name(internal_name: str) -> str:
    """Convert tool name from snake_case to PascalCase automatically.

    Args:
        internal_name: Tool name in snake_case (e.g., "read_file", "run_command")

    Returns:
        PascalCase display name (e.g., "ReadFile", "RunCommand")

    Examples:
        >>> get_tool_display_name("read_file")
        'ReadFile'
        >>> get_tool_display_name("run_command")
        'RunCommand'
        >>> get_tool_display_name("ls")
        'Ls'
        >>> get_tool_display_name("unknown_tool")
        'UnknownTool'
    """
    # Auto-convert snake_case to PascalCase
    # e.g., "read_file" -> "ReadFile", "run_command" -> "RunCommand"
    return internal_name.replace("_", " ").title().replace(" ", "")
