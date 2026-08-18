"""Tool metadata registry and display utilities.

This package provides the canonical tool display metadata registry
used by CLI, TUI, and formatting utilities to present tools consistently.

The registry includes:
- Tool display names and aliases
- Path argument indicators (which tools take file/workspace paths)
- Header-style tool names for TUI
- Outcome type classification for event handling
"""

__all__ = [
    "ToolMeta",
    "TOOL_REGISTRY",
    "get_tool_meta",
    "get_all_path_arg_keys",
    "get_tool_display_name",
    "get_tools_with_header_info",
    "get_tool_categories",
    "get_outcome_type",
    "is_policy_filesystem_tool",
    "extract_filesystem_path_for_policy",
]

from soothe_sdk.tools.metadata import (
    TOOL_REGISTRY,
    ToolMeta,
    extract_filesystem_path_for_policy,
    get_all_path_arg_keys,
    get_outcome_type,
    get_tool_categories,
    get_tool_display_name,
    get_tool_meta,
    get_tools_with_header_info,
    is_policy_filesystem_tool,
)
