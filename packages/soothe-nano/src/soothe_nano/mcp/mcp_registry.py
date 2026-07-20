"""Daemon-singleton registry for MCP server connections and capabilities."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import BaseTool

from soothe_nano.config.models import MCPServerConfig, MCPTransport
from soothe_nano.mcp.mcp_config import interpolate_auth_headers, make_connection_spec
from soothe_nano.mcp.mcp_events import (
    emit_server_connect_failed,
    emit_server_connected,
    emit_server_disconnected,
)
from soothe_nano.mcp.mcp_registry_support import (
    cleanup_remote_connection,
    cleanup_stdio_connection,
    fetch_prompts,
    fetch_resources,
    fetch_tools_and_descriptors,
    invoke_tool,
    read_resource,
)
from soothe_nano.mcp.mcp_utils import MCPConnection, MCPToolDescriptor
from soothe_nano.mcp.reconnect import schedule_reconnect

logger = logging.getLogger(__name__)

__all__ = ["MCPRegistry"]

STDIO_BATCH_SIZE = 3
REMOTE_BATCH_SIZE = 20


class MCPRegistry:
    """Connection manager wrapping MultiServerMCPClient."""

    def __init__(
        self,
        servers: list[MCPServerConfig],
        secret_resolver: callable | None = None,
    ) -> None:
        self._servers = servers
        self._secret_resolver = secret_resolver or (lambda x: x)
        self._client: Any = None
        self._connections: dict[str, MCPConnection] = {}
        self._tools: dict[str, list[BaseTool]] = {}
        self._tool_descriptors: dict[str, list[MCPToolDescriptor]] = {}
        self._prompts: dict[str, list[dict]] = {}
        self._resources: dict[str, list[dict]] = {}
        self._defer: dict[str, bool] = {}
        self._initialized = False
        self._shutdown_event = asyncio.Event()

    async def initialize(self) -> None:
        """Connect all enabled servers concurrently."""
        if self._initialized:
            logger.warning("[MCP] Registry already initialized")
            return

        enabled = [server for server in self._servers if server.enabled]
        if not enabled:
            logger.info("[MCP] No enabled MCP servers to connect")
            self._initialized = True
            return

        resolved_servers: list[tuple[MCPServerConfig, dict[str, str], dict[str, str]]] = []
        for server in enabled:
            resolved_env = {key: self._secret_resolver(value) for key, value in server.env.items()}
            resolved_headers: dict[str, str] = {}
            if server.auth and server.auth.headers:
                resolved_headers = interpolate_auth_headers(
                    server.auth.headers, self._secret_resolver
                )
            resolved_servers.append((server, resolved_env, resolved_headers))

        connections: dict[str, Any] = {}
        for server, env, headers in resolved_servers:
            spec = make_connection_spec(server)
            if server.transport == MCPTransport.STDIO:
                spec["env"] = env if env else None
            elif server.transport in (MCPTransport.SSE, MCPTransport.STREAMABLE_HTTP):
                spec["headers"] = headers if headers else None
            connections[server.name] = spec
            self._defer[server.name] = server.defer

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            self._client = MultiServerMCPClient(connections, tool_name_prefix=False)
        except ImportError as error:
            logger.error("[MCP] Failed to import langchain_mcp_adapters: %s", error)
            for server in enabled:
                emit_server_connect_failed(
                    server.name,
                    server.transport.value,
                    "ImportError",
                    attempt=0,
                    is_terminal=True,
                )
            return

        stdio_servers = [server for server in enabled if server.transport == MCPTransport.STDIO]
        remote_servers = [server for server in enabled if server.transport != MCPTransport.STDIO]
        logger.info(
            "[MCP] Connecting %d servers (%d stdio, %d remote)",
            len(enabled),
            len(stdio_servers),
            len(remote_servers),
        )

        connect_tasks = [self._connect_server(server.name) for server in stdio_servers]
        connect_tasks.extend(self._connect_server(server.name) for server in remote_servers)

        results = await asyncio.gather(*connect_tasks, return_exceptions=True)
        connected = sum(1 for result in results if result is None or result == "connected")
        failed = sum(1 for result in results if isinstance(result, Exception) or result == "failed")
        logger.info("[MCP] Initialized: %d connected, %d failed", connected, failed)
        self._initialized = True

    async def _connect_server(self, name: str) -> str:
        """Connect one server and fetch tools/prompts/resources."""
        server_cfg = next((server for server in self._servers if server.name == name), None)
        if not server_cfg:
            return "failed"

        start_time = datetime.now(UTC)
        try:
            async with self._client.session(name, auto_initialize=True) as session:
                tools_task = asyncio.to_thread(
                    fetch_tools_and_descriptors,
                    self._client,
                    server_name=name,
                    server_cfg=server_cfg,
                )
                prompts_task = fetch_prompts(session, server_name=name)
                resources_task = fetch_resources(session, server_name=name)
                tools_result, prompts_result, resources_result = await asyncio.gather(
                    tools_task,
                    prompts_task,
                    resources_task,
                    return_exceptions=True,
                )

                if isinstance(tools_result, Exception):
                    logger.warning("[MCP] Failed to fetch tools from %s: %s", name, tools_result)
                    tools: list[BaseTool] = []
                    descriptors: list[MCPToolDescriptor] = []
                else:
                    tools, descriptors = tools_result

                if isinstance(prompts_result, Exception):
                    logger.warning(
                        "[MCP] Failed to fetch prompts from %s: %s", name, prompts_result
                    )
                    prompts: list[dict] = []
                else:
                    prompts = prompts_result

                if isinstance(resources_result, Exception):
                    logger.warning(
                        "[MCP] Failed to fetch resources from %s: %s", name, resources_result
                    )
                    resources: list[dict] = []
                else:
                    resources = resources_result

                latency_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                conn = MCPConnection(
                    name=name,
                    transport=server_cfg.transport,
                    status="connected",
                    tool_count=len(tools),
                    prompt_count=len(prompts),
                    resource_count=len(resources),
                    connected_at=start_time,
                    _session=session,
                )
                self._connections[name] = conn
                self._tools[name] = tools
                self._tool_descriptors[name] = descriptors
                self._prompts[name] = prompts
                self._resources[name] = resources

                emit_server_connected(
                    name,
                    server_cfg.transport.value,
                    conn.tool_count,
                    conn.prompt_count,
                    conn.resource_count,
                    latency_ms,
                )
                return "connected"
        except Exception as error:  # noqa: BLE001
            logger.error("[MCP] Failed to connect %s: %s", name, error)
            emit_server_connect_failed(
                name,
                server_cfg.transport.value,
                type(error).__name__,
                attempt=0,
                is_terminal=server_cfg.transport == MCPTransport.STDIO,
            )
            if server_cfg.transport != MCPTransport.STDIO:
                self._connections[name] = MCPConnection(
                    name=name,
                    transport=server_cfg.transport,
                    status="connect_failed",
                    last_error=str(error),
                )
                await schedule_reconnect(self, name, server_cfg)
            return "failed"

    async def shutdown(self, deadline_seconds: float = 5.0) -> None:
        """Close all connections with an aggregate deadline."""
        if not self._initialized:
            return

        self._shutdown_event.set()
        deadline = asyncio.get_event_loop().time() + deadline_seconds
        logger.info("[MCP] Shutting down registry (deadline %.1fs)", deadline_seconds)

        cleanup_tasks = []
        for name, connection in self._connections.items():
            if connection.transport == MCPTransport.STDIO:
                cleanup_tasks.append(cleanup_stdio_connection(self, name, deadline))
            else:
                cleanup_tasks.append(cleanup_remote_connection(self, name))
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception as error:  # noqa: BLE001
                logger.warning("[MCP] Error closing client: %s", error)

        self._initialized = False
        logger.info("[MCP] Registry shutdown complete")

    def always_loaded_tools(self, workspace: str | None = None) -> list[BaseTool]:
        """Return tools from servers where defer=False."""
        result: list[BaseTool] = []
        for name, defer in self._defer.items():
            if not defer and name in self._tools:
                result.extend(self._tools[name])
        return result

    def all_tools(self, workspace: str | None = None) -> list[BaseTool]:
        """Return all MCP tools from all connected servers."""
        result: list[BaseTool] = []
        for tools in self._tools.values():
            result.extend(tools)
        return result

    def deferred_tools(self, workspace: str | None = None) -> list[MCPToolDescriptor]:
        """Return deferred MCP tool descriptors."""
        result: list[MCPToolDescriptor] = []
        for name, defer in self._defer.items():
            if defer and name in self._tool_descriptors:
                result.extend(self._tool_descriptors[name])
        return result

    def prompts(self) -> dict[str, list[dict]]:
        """Return per-server prompt descriptors."""
        return dict(self._prompts)

    def resources(self) -> dict[str, list[dict]]:
        """Return per-server resource descriptors."""
        return dict(self._resources)

    async def invoke(self, server: str, tool: str, args: dict) -> Any:
        """Invoke a server tool by mangled tool name."""
        return await invoke_tool(self, server, tool, args)

    async def read_resource(self, server: str, uri: str) -> str:
        """Read a resource by URI from a server."""
        return await read_resource(self, server, uri)

    def connection_status(self) -> dict[str, MCPConnection]:
        """Return current status of all connections."""
        return dict(self._connections)

    def subscribe_list_changed(self) -> None:
        """Arm list_changed notification handlers placeholder."""
        logger.debug("[MCP] list_changed subscription armed (placeholder)")

    def register_thread(self, thread_id: str, workspace: str | None) -> None:
        """Register a thread for cleanup tracking placeholder."""
        logger.debug("[MCP] Thread %s registered with workspace %s", thread_id, workspace)

    async def handle_disconnect(self, name: str) -> None:
        """Mark disconnected state and emit disconnect event."""
        conn = self._connections.get(name)
        if conn:
            conn.status = "disconnected"
            emit_server_disconnected(name, "transport_error", was_clean=False)

    async def handle_reconnect_success(self, name: str) -> None:
        """Reconnect helper callback used by scheduler."""
        server_cfg = next((server for server in self._servers if server.name == name), None)
        if server_cfg:
            await self._connect_server(name)
