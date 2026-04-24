"""Tool display names for user-facing messages.

DEPRECATED: Use `soothe_sdk.utils.tool_meta.get_tool_display_name` instead.

This module is deprecated and will be removed in a future release.
The canonical `ToolMeta` registry in the SDK provides unified display metadata.
"""

from __future__ import annotations

import warnings


def get_tool_display_name(internal_name: str) -> str:
    """Convert tool name from snake_case to PascalCase automatically.

    DEPRECATED: Use `soothe_sdk.utils.tool_meta.get_tool_display_name` instead.

    Args:
        internal_name: Tool name in snake_case (e.g., "read_file", "run_command")

    Returns:
        PascalCase display name (e.g., "ReadFile", "RunCommand")
    """
    warnings.warn(
        "soothe.toolkits.display_names.get_tool_display_name is deprecated. "
        "Use soothe_sdk.utils.tool_meta.get_tool_display_name instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Delegate to the canonical implementation
    from soothe_sdk.utils.tool_meta import get_tool_display_name

    return get_tool_display_name(internal_name)
