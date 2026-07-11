"""Backward-compat adapter for legacy thread-manager MCP imports (RFC-412).

Prefer the daemon-owned ``MCPRegistry`` singleton. This module remains for
``ThreadContextManager._ensure_mcp_session`` until that path is removed.
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

    # Full catalog for progressive binding; ThreadContextManager legacy path only.
    tools = registry.all_tools()

    return (tools, MCPSessionManager(registry))
