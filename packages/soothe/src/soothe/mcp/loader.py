"""MCP loader — backward-compat adapter for manager.py imports (RFC-412).

Provides load_mcp_tools and MCPSessionManager to satisfy the imports in
core/thread/manager.py:24,553 until those imports are replaced.

TODO (Batch 2): Replace manager.py imports with registry registration.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.config.models import MCPServerConfig

logger = logging.getLogger(__name__)

__all__ = ["load_mcp_tools", "MCPSessionManager"]


class MCPSessionManager:
    """Backward-compat wrapper around MCPRegistry (RFC-412).

    Provides cleanup() method expected by manager.py.
    """

    def __init__(self, registry: Any) -> None:
        """Initialize wrapper.

        Args:
            registry: MCPRegistry instance to wrap.
        """
        self._registry = registry

    async def cleanup(self) -> None:
        """Cleanup MCP session (delegates to registry shutdown)."""
        if self._registry is not None:
            try:
                await self._registry.shutdown(deadline_seconds=5.0)
            except Exception as e:
                logger.warning("[MCP] Session cleanup error: %s", e)


async def load_mcp_tools(
    servers: list[MCPServerConfig],
    secret_resolver: callable | None = None,
) -> tuple[list[Any], MCPSessionManager]:
    """Load MCP tools via MCPRegistry (RFC-412).

    Args:
        servers: List of MCPServerConfig from SootheConfig.
        secret_resolver: Function to resolve ${ENV_VAR} placeholders.

    Returns:
        Tuple of (tool list, MCPSessionManager wrapper).
    """
    from soothe.mcp.registry import MCPRegistry

    registry = MCPRegistry(servers=servers, secret_resolver=secret_resolver)
    await registry.initialize()

    # Get always-loaded tools (defer=False servers)
    tools = registry.always_loaded_tools()

    return (tools, MCPSessionManager(registry))
