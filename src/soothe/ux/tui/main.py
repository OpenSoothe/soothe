"""Optional tools checker and session MCP preloader for TUI (stub from deepagents-cli migration).

This module provides optional tools checking and MCP server preloading functionality.
"""

import logging

logger = logging.getLogger(__name__)


def check_optional_tools() -> list[str]:
    """Check for optional CLI tools that may not be installed.

    Stub - returns empty list.
    Full implementation should check for optional dependencies like:
    - ripgrep (rg)
    - fd
    - etc.

    Returns:
        List of missing optional tool names.
    """
    # Stub - no missing tools
    return []


def format_tool_warning_tui(tool_name: str) -> str:
    """Format a warning message for missing optional tool in TUI.

    Args:
        tool_name: Name of the missing tool.

    Returns:
        Formatted warning message string.
    """
    return f"Optional tool '{tool_name}' not installed. Some features may be limited."


def _preload_session_mcp_server_info(thread_id: str | None = None) -> dict:
    """Preload MCP server information for a session thread.

    Stub - returns empty dict.
    Full implementation should load MCP server configuration
    from thread state or config.

    Args:
        thread_id: Thread ID to preload MCP info for.

    Returns:
        Dictionary with MCP server information.
    """
    # Stub - no MCP server info
    return {}
