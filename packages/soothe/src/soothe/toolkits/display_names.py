"""Tool display names for user-facing messages.

Delegates to ``soothe_sdk.tools.metadata.get_tool_display_name``.
"""

from __future__ import annotations


def get_tool_display_name(internal_name: str) -> str:
    """Convert tool name from snake_case to PascalCase for display.

    Args:
        internal_name: Tool name in snake_case (e.g., ``read_file``, ``run_command``).

    Returns:
        PascalCase display name (e.g., ``ReadFile``, ``RunCommand``).
    """
    from soothe_sdk.tools.metadata import get_tool_display_name as sdk_get_tool_display_name

    return sdk_get_tool_display_name(internal_name)
