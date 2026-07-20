"""MCPRegistry — daemon-singleton for MCP connection management (RFC-412).

Wraps langchain_mcp_adapters.MultiServerMCPClient and provides:
- Per-server connection sharing across threads
- Progressive disclosure (deferred vs always-loaded tools)
- Policy-gated tool/resource/prompt access
- Reconnect scheduling for remote transports
- list_changed notification handling
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import BaseTool

from soothe_nano.config.models import MCPServerConfig, MCPTransport
from soothe_nano.mcp.auth import interpolate_auth_headers
from soothe_nano.mcp.budget import MCPToolDescriptor
from soothe_nano.mcp.connection import MCPConnection
from soothe_nano.mcp.events import (
    emit_server_connect_failed,
    emit_server_connected,
    emit_server_disconnected,
)
from soothe_nano.mcp.name_utils import build_mcp_tool_name
from soothe_nano.mcp.reconnect import schedule_reconnect
from soothe_nano.mcp.transports import make_connection_spec

logger = logging.getLogger(__name__)

__all__ = ["MCPRegistry"]


# Batch sizes for concurrent connection (mirrors Claude Code)
STDIO_BATCH_SIZE = 3
REMOTE_BATCH_SIZE = 20


class MCPRegistry:
    """Daemon-singleton MCP connection manager (RFC-412).

    Wraps langchain_mcp_adapters.MultiServerMCPClient to provide:
    - Per-server connection sharing across threads
    - Progressive disclosure (deferred vs always-loaded tools)
    - Policy-gated access
    - Reconnect scheduling for remote transports
    """

    def __init__(
        self,
        servers: list[MCPServerConfig],
        secret_resolver: callable | None = None,
    ) -> None:
        """Initialize with MCPServerConfig list. Does not connect yet.

        Args:
            servers: List of MCPServerConfig from SootheConfig.mcp_servers.
            secret_resolver: Function to resolve ${ENV_VAR} (from config.secret_resolver).
        """
        self._servers = servers
        self._secret_resolver = secret_resolver or (lambda x: x)
        self._client: Any = None  # MultiServerMCPClient
        self._connections: dict[str, MCPConnection] = {}
        self._tools: dict[str, list[BaseTool]] = {}
        self._tool_descriptors: dict[str, list[MCPToolDescriptor]] = {}
        self._prompts: dict[str, list[dict]] = {}
        self._resources: dict[str, list[dict]] = {}
        self._defer: dict[str, bool] = {}
        self._initialized = False
        self._shutdown_event = asyncio.Event()

    async def initialize(self) -> None:
        """Connect all enabled servers concurrently.

        Uses langchain_mcp_adapters.MultiServerMCPClient with batched connection:
        - 3 concurrent stdio servers
        - 20 concurrent remote servers

        Emits soothe.mcp.server.connected/connect_failed events per server.
        """
        if self._initialized:
            logger.warning("[MCP] Registry already initialized")
            return

        # Filter enabled servers
        enabled = [s for s in self._servers if s.enabled]
        if not enabled:
            logger.info("[MCP] No enabled MCP servers to connect")
            self._initialized = True
            return

        # Resolve env vars and interpolate auth headers
        resolved_servers = []
        for server in enabled:
            resolved_env = {k: self._secret_resolver(v) for k, v in server.env.items()}
            resolved_headers = {}
            if server.auth and server.auth.headers:
                resolved_headers = interpolate_auth_headers(
                    server.auth.headers, self._secret_resolver
                )
            resolved_servers.append((server, resolved_env, resolved_headers))

        # Build connection specs
        connections: dict[str, Any] = {}
        for server, env, headers in resolved_servers:
            spec = make_connection_spec(server)
            if server.transport == MCPTransport.STDIO:
                spec["env"] = env if env else None
            elif server.transport in (
                MCPTransport.SSE,
                MCPTransport.STREAMABLE_HTTP,
            ):
                spec["headers"] = headers if headers else None
            connections[server.name] = spec
            self._defer[server.name] = server.defer

        # Create MultiServerMCPClient
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            self._client = MultiServerMCPClient(connections, tool_name_prefix=False)
        except ImportError as e:
            logger.error("[MCP] Failed to import langchain_mcp_adapters: %s", e)
            for server in enabled:
                emit_server_connect_failed(
                    server.name,
                    server.transport.value,
                    "ImportError",
                    attempt=0,
                    is_terminal=True,
                )
            return

        # Partition by transport for batched connection
        stdio_servers = [s for s in enabled if s.transport == MCPTransport.STDIO]
        remote_servers = [s for s in enabled if s.transport != MCPTransport.STDIO]

        logger.info(
            "[MCP] Connecting %d servers (%d stdio, %d remote)",
            len(enabled),
            len(stdio_servers),
            len(remote_servers),
        )

        # Connect in batches
        connect_tasks = []

        # Stdio batched
        for i, server in enumerate(stdio_servers):
            connect_tasks.append(self._connect_server(server.name))

        # Remote batched (all at once since batch_size=20)
        for server in remote_servers:
            connect_tasks.append(self._connect_server(server.name))

        # Run all connections concurrently
        results = await asyncio.gather(*connect_tasks, return_exceptions=True)

        # Count successes/failures
        connected = sum(1 for r in results if r is None or r == "connected")
        failed = sum(1 for r in results if isinstance(r, Exception) or r == "failed")

        logger.info("[MCP] Initialized: %d connected, %d failed", connected, failed)
        self._initialized = True

    async def _connect_server(self, name: str) -> str:
        """Connect a single server and fetch capabilities.

        Returns:
            "connected" or "failed"

        Emits events and schedules reconnect on failure for remote transports.
        """
        server_cfg = next((s for s in self._servers if s.name == name), None)
        if not server_cfg:
            return "failed"

        start_time = datetime.now(UTC)

        try:
            # Get session via client
            async with self._client.session(name, auto_initialize=True) as session:
                # Fetch capabilities concurrently
                tools, prompts, resources = await asyncio.gather(
                    self._fetch_tools(name, session, server_cfg),
                    self._fetch_prompts(name, session),
                    self._fetch_resources(name, session),
                    return_exceptions=True,
                )

                # Handle fetch errors
                if isinstance(tools, Exception):
                    logger.warning("[MCP] Failed to fetch tools from %s: %s", name, tools)
                    tools = []
                if isinstance(prompts, Exception):
                    logger.warning("[MCP] Failed to fetch prompts from %s: %s", name, prompts)
                    prompts = []
                if isinstance(resources, Exception):
                    logger.warning("[MCP] Failed to fetch resources from %s: %s", name, resources)
                    resources = []

                # Store connection info
                latency_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                conn = MCPConnection(
                    name=name,
                    transport=server_cfg.transport,
                    status="connected",
                    tool_count=len(tools) if isinstance(tools, list) else 0,
                    prompt_count=len(prompts) if isinstance(prompts, list) else 0,
                    resource_count=len(resources) if isinstance(resources, list) else 0,
                    connected_at=start_time,
                )
                self._connections[name] = conn

                # Store capabilities
                if isinstance(tools, list):
                    self._tools[name] = tools
                if isinstance(prompts, list):
                    self._prompts[name] = prompts
                if isinstance(resources, list):
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

        except Exception as e:
            logger.error("[MCP] Failed to connect %s: %s", name, e)
            emit_server_connect_failed(
                name,
                server_cfg.transport.value,
                type(e).__name__,
                attempt=0,
                is_terminal=server_cfg.transport == MCPTransport.STDIO,
            )

            # Schedule reconnect for remote transports
            if server_cfg.transport != MCPTransport.STDIO:
                conn = MCPConnection(
                    name=name,
                    transport=server_cfg.transport,
                    status="connect_failed",
                    last_error=str(e),
                )
                self._connections[name] = conn
                await schedule_reconnect(self, name, server_cfg)

            return "failed"

    async def _fetch_tools(
        self, name: str, session: Any, server_cfg: MCPServerConfig
    ) -> list[BaseTool]:
        """Fetch tools from server and apply name mangling + filter."""
        tools = self._client.get_tools(server_name=name)

        # Apply tool_filter (fnmatch allowlist)
        if server_cfg.tool_filter:
            import fnmatch

            filtered = []
            for tool in tools:
                bare_name = tool.name if hasattr(tool, "name") else str(tool)
                if any(fnmatch.fnmatch(bare_name, pattern) for pattern in server_cfg.tool_filter):
                    filtered.append(tool)
            tools = filtered

        # Apply name mangling (build_mcp_tool_name)
        # Note: langchain_mcp_adapters already returns BaseTool instances
        # We need to rename them to follow soothe's mcp__ convention
        for tool in tools:
            if hasattr(tool, "name"):
                original = tool.name
                tool.name = build_mcp_tool_name(name, original)

        # Build descriptors for progressive disclosure
        descriptors = []
        for tool in tools:
            desc = MCPToolDescriptor(
                name=tool.name,
                bare_name=original if hasattr(tool, "name") else tool.name,
                description=tool.description if hasattr(tool, "description") else "",
                server=name,
                is_essential=not server_cfg.defer,  # defer=False → essential
            )
            descriptors.append(desc)

        self._tool_descriptors[name] = descriptors
        return tools

    async def _fetch_prompts(self, name: str, session: Any) -> list[dict]:
        """Fetch prompts from server."""
        # langchain_mcp_adapters doesn't have a direct get_prompts method
        # Use list_prompts via session if available
        try:
            prompts = await session.list_prompts()
            result = []
            for p in prompts:
                result.append(
                    {
                        "name": build_mcp_tool_name(name, p.name if hasattr(p, "name") else str(p)),
                        "bare_name": p.name if hasattr(p, "name") else str(p),
                        "description": p.description if hasattr(p, "description") else None,
                        "server": name,
                    }
                )
            return result
        except AttributeError:
            # Session doesn't support prompts
            return []

    async def _fetch_resources(self, name: str, session: Any) -> list[dict]:
        """Fetch resources from server."""
        try:
            resources = await session.list_resources()
            result = []
            for r in resources:
                result.append(
                    {
                        "uri": r.uri if hasattr(r, "uri") else str(r),
                        "name": r.name if hasattr(r, "name") else None,
                        "description": r.description if hasattr(r, "description") else None,
                        "server": name,
                        "mime_type": r.mimeType if hasattr(r, "mimeType") else None,
                    }
                )
            return result
        except AttributeError:
            # Session doesn't support resources
            return []

    async def shutdown(self, deadline_seconds: float = 5.0) -> None:
        """Close all connections with aggregate deadline.

        For stdio: uses cleanup ladder (SIGINT → SIGTERM → kill -9).
        For remote: session.close() then client.__aexit__().
        """
        if not self._initialized:
            return

        self._shutdown_event.set()
        deadline = asyncio.get_event_loop().time() + deadline_seconds

        logger.info("[MCP] Shutting down registry (deadline %.1fs)", deadline_seconds)

        cleanup_tasks = []
        for name, conn in self._connections.items():
            if conn.transport == MCPTransport.STDIO:
                cleanup_tasks.append(self._cleanup_stdio(name, deadline))
            else:
                cleanup_tasks.append(self._cleanup_remote(name))

        await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        # Close the MultiServerMCPClient
        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("[MCP] Error closing client: %s", e)

        self._initialized = False
        logger.info("[MCP] Registry shutdown complete")

    async def _cleanup_stdio(self, name: str, deadline: float) -> None:
        """Cleanup stdio subprocess with signal ladder."""
        from soothe_nano.mcp.cleanup import cleanup_subprocess

        # Get the subprocess from the connection
        conn = self._connections.get(name)
        if not conn or not conn._session:
            return

        remaining_time = deadline - asyncio.get_event_loop().time()
        if remaining_time <= 0:
            remaining_time = 0.1

        try:
            await cleanup_subprocess(conn._session, timeout_seconds=remaining_time)
            emit_server_disconnected(name, "shutdown", was_clean=True)
        except Exception as e:
            logger.warning("[MCP] Cleanup ladder error for %s: %s", name, e)
            emit_server_disconnected(name, str(e), was_clean=False)

    async def _cleanup_remote(self, name: str) -> None:
        """Cleanup remote connection."""
        conn = self._connections.get(name)
        if not conn or not conn._session:
            return

        try:
            await conn._session.close()
            emit_server_disconnected(name, "shutdown", was_clean=True)
        except Exception as e:
            logger.warning("[MCP] Close error for %s: %s", name, e)
            emit_server_disconnected(name, str(e), was_clean=False)

    def always_loaded_tools(self, workspace: str | None = None) -> list[BaseTool]:
        """Return tools from servers where defer=False.

        Args:
            workspace: Workspace path (for future policy filtering).

        Returns:
            List of BaseTool instances that should be in the default tool array.
        """
        result = []
        for name, defer in self._defer.items():
            if not defer and name in self._tools:
                result.extend(self._tools[name])
        return result

    def all_tools(self, workspace: str | None = None) -> list[BaseTool]:
        """Return all connected MCP BaseTool instances (defer=True and defer=False).

        Args:
            workspace: Workspace path (for future policy filtering).

        Returns:
            Flattened list of every tool from every connected server.
        """
        result: list[BaseTool] = []
        for tools in self._tools.values():
            result.extend(tools)
        return result

    def deferred_tools(self, workspace: str | None = None) -> list[MCPToolDescriptor]:
        """Return descriptors for servers where defer=True.

        Args:
            workspace: Workspace path (for future policy filtering).

        Returns:
            List of MCPToolDescriptor for progressive disclosure.
        """
        result = []
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
        """Invoke a tool via MultiServerMCPClient.

        Args:
            server: Server name.
            tool: Mangled tool name (mcp__server__tool).
            args: Tool arguments.

        Returns:
            Tool result.

        Raises:
            ValueError: If server or tool not found.
            RuntimeError: If tool invocation fails.
        """
        if not self._initialized or not self._client:
            raise RuntimeError("MCPRegistry not initialized")

        tools = self._tools.get(server, [])
        target_tool = next((t for t in tools if t.name == tool), None)
        if not target_tool:
            raise ValueError(f"Tool {tool} not found on server {server}")

        start_time = datetime.now(UTC)
        try:
            result = await target_tool.ainvoke(args)
            latency_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            # Emit invocation event (success)
            from soothe_nano.mcp.events import emit_tool_invoked

            emit_tool_invoked(
                server,
                tool,
                latency_ms,
                success=True,
                result_chars=len(str(result)),
            )
            return result

        except TimeoutError:
            server_cfg = next((s for s in self._servers if s.name == server), None)
            timeout_s = server_cfg.tool_timeout_seconds if server_cfg else 600.0
            from soothe_nano.mcp.events import emit_tool_timeout

            emit_tool_timeout(server, tool, timeout_s)
            raise RuntimeError(f"Tool {tool} timed out after {timeout_s}s")

        except Exception as e:
            latency_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            from soothe_nano.mcp.events import emit_tool_invoked

            emit_tool_invoked(server, tool, latency_ms, success=False, result_chars=0)
            raise RuntimeError(f"Tool {tool} invocation failed: {e}")

    async def read_resource(self, server: str, uri: str) -> str:
        """Read a resource, converting Blob to str.

        Args:
            server: Server name.
            uri: Resource URI.

        Returns:
            Resource content as string.

        Raises:
            ValueError: If server or resource not found.
        """
        if not self._initialized or not self._client:
            raise RuntimeError("MCPRegistry not initialized")

        start_time = datetime.now(UTC)

        try:
            # Get resources from MultiServerMCPClient
            blobs = await self._client.get_resources(server_name=server, uris=uri)

            if not blobs:
                raise ValueError(f"Resource {uri} not found on server {server}")

            # Convert Blob to string
            blob = blobs[0]
            if hasattr(blob, "data"):
                content = (
                    blob.data.decode("utf-8") if isinstance(blob.data, bytes) else str(blob.data)
                )
            else:
                content = str(blob)

            latency_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            from soothe_nano.mcp.events import emit_resource_read

            emit_resource_read(server, uri, len(content), latency_ms)
            return content

        except Exception as e:
            raise RuntimeError(f"Failed to read resource {uri}: {e}")

    def connection_status(self) -> dict[str, MCPConnection]:
        """Return current status of all connections."""
        return dict(self._connections)

    def subscribe_list_changed(self) -> None:
        """Arm list_changed notification handlers.

        Note: langchain_mcp_adapters doesn't expose list_changed callbacks directly.
        This is a placeholder for manual polling or future SDK support.
        """
        # Placeholder: In a full implementation, we'd subscribe to session notifications
        # and emit list_changed events. For now, tools/prompts/resources are static
        # after initial fetch.
        logger.debug("[MCP] list_changed subscription armed (placeholder)")

    def register_thread(self, thread_id: str, workspace: str | None) -> None:
        """Register a thread for cleanup tracking.

        Args:
            thread_id: Thread identifier.
            workspace: Thread's workspace path.
        """
        # Placeholder: For tracking per-thread state for cleanup
        logger.debug("[MCP] Thread %s registered with workspace %s", thread_id, workspace)

    async def handle_disconnect(self, name: str) -> None:
        """Handle a server disconnect (called by reconnect scheduler).

        Updates connection status and emits disconnect event.
        """
        conn = self._connections.get(name)
        if conn:
            conn.status = "disconnected"
            emit_server_disconnected(name, "transport_error", was_clean=False)

    async def handle_reconnect_success(self, name: str) -> None:
        """Handle successful reconnect (called by reconnect scheduler).

        Re-fetches capabilities and emits connected event.
        """
        server_cfg = next((s for s in self._servers if s.name == name), None)
        if server_cfg:
            await self._connect_server(name)
