"""MCP server loading for Soothe, wrapping langchain-mcp-adapters.

Supports stdio and HTTP/SSE transports in Claude Desktop `.mcp.json` format.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from langchain_mcp_adapters.client import Connection

from soothe.config import MCPServerConfig

logger = logging.getLogger(__name__)

_REMOTE_TRANSPORTS = {"sse", "http"}


@dataclass
class MCPSessionManager:
    """Manages MCP client sessions for cleanup."""

    client: Any = None
    exit_stack: AsyncExitStack = field(default_factory=AsyncExitStack)

    async def cleanup(self) -> None:
        """Close all managed sessions."""
        await self.exit_stack.aclose()


def _build_connection(name: str, cfg: MCPServerConfig) -> tuple[str, Connection]:
    """Convert a SootheConfig MCP entry to a langchain-mcp-adapters connection.

    Args:
        name: Logical server name.
        cfg: MCP server configuration.

    Returns:
        Tuple of `(server_name, connection_dict)`.
    """
    from langchain_mcp_adapters.sessions import (
        SSEConnection,
        StdioConnection,
        StreamableHttpConnection,
    )

    transport = cfg.transport.lower()

    if transport in _REMOTE_TRANSPORTS and cfg.url:
        if transport == "http":
            conn: Connection = StreamableHttpConnection(
                transport="streamable_http",
                url=cfg.url,
            )
        else:
            conn = SSEConnection(transport="sse", url=cfg.url)
        return name, conn

    conn = StdioConnection(
        command=cfg.command or "",
        args=cfg.args,
        env=cfg.env or None,
        transport="stdio",
    )
    return name, conn


async def load_mcp_tools(
    servers: list[MCPServerConfig],
) -> tuple[list[BaseTool], MCPSessionManager]:
    """Load tools from MCP servers.

    Args:
        servers: List of MCP server configurations.

    Returns:
        Tuple of `(tools, session_manager)`.  Caller must call
        `session_manager.cleanup()` when done.

    Raises:
        RuntimeError: If server connection or tool loading fails.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.tools import load_mcp_tools as _load

    if not servers:
        return [], MCPSessionManager()

    connections: dict[str, Connection] = {}
    for idx, cfg in enumerate(servers):
        server_name = f"mcp-{idx}"
        _, conn = _build_connection(server_name, cfg)
        connections[server_name] = conn

    manager = MCPSessionManager()

    try:
        client = MultiServerMCPClient(connections=connections)
        manager.client = client
    except Exception as exc:
        await manager.cleanup()
        msg = f"Failed to initialise MCP client: {exc}"
        raise RuntimeError(msg) from exc

    all_tools: list[BaseTool] = []
    try:
        for server_name in connections:
            session = await manager.exit_stack.enter_async_context(client.session(server_name))
            tools = await _load(session, server_name=server_name, tool_name_prefix=True)
            all_tools.extend(tools)
            logger.info("Loaded %d tools from MCP server '%s'", len(tools), server_name)
    except Exception as exc:
        await manager.cleanup()
        msg = f"Failed to load MCP tools: {exc}"
        raise RuntimeError(msg) from exc

    return all_tools, manager
