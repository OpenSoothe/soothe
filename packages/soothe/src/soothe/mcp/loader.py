"""MCP loader — backward-compat adapter for manager.py imports (RFC-412).

Provides load_mcp_tools and MCPSessionManager to satisfy the imports in
core/thread/manager.py:24,553 until those imports are replaced.

TODO (Batch 2): Replace manager.py imports with registry registration.
"""

from __future__ import annotations

from typing import Any

__all__ = ["load_mcp_tools", "MCPSessionManager"]


class MCPSessionManager:
    """Stub for backward compat with manager.py imports (RFC-412 Batch 1).

    The real implementation in Batch 2 will delegate to MCPRegistry.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def cleanup(self) -> None:
        """Cleanup MCP session (stub)."""
        pass


async def load_mcp_tools(servers: list) -> tuple:
    """Stub load_mcp_tools for backward compat (RFC-412 Batch 1).

    Returns empty tuple and stub manager. The real implementation
    in Batch 2 will use MCPRegistry.

    Args:
        servers: list of MCPServerConfig (ignored in stub).

    Returns:
        (empty list, MCPSessionManager stub)
    """
    return ([], MCPSessionManager())
