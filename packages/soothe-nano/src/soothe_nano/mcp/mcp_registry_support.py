"""Support functions for MCPRegistry capability fetch and cleanup."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool

from soothe_nano.config.models import MCPServerConfig
from soothe_nano.mcp.cleanup import cleanup_subprocess
from soothe_nano.mcp.mcp_events import (
    emit_resource_read,
    emit_server_disconnected,
    emit_tool_invoked,
    emit_tool_timeout,
)
from soothe_nano.mcp.mcp_utils import MCPToolDescriptor, build_mcp_tool_name

if TYPE_CHECKING:
    from soothe_nano.mcp.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)


def fetch_tools_and_descriptors(
    client: Any,
    *,
    server_name: str,
    server_cfg: MCPServerConfig,
) -> tuple[list[BaseTool], list[MCPToolDescriptor]]:
    """Fetch tools from a server, applying filter and name mangling."""
    tools = client.get_tools(server_name=server_name)
    if server_cfg.tool_filter:
        filtered: list[BaseTool] = []
        for tool in tools:
            bare_name = tool.name if hasattr(tool, "name") else str(tool)
            if any(fnmatch.fnmatch(bare_name, pattern) for pattern in server_cfg.tool_filter):
                filtered.append(tool)
        tools = filtered

    descriptors: list[MCPToolDescriptor] = []
    for tool in tools:
        if hasattr(tool, "name"):
            bare_name = str(tool.name)
            tool.name = build_mcp_tool_name(server_name, bare_name)
        else:
            bare_name = str(tool)
        descriptors.append(
            MCPToolDescriptor(
                name=tool.name,
                bare_name=bare_name,
                description=tool.description if hasattr(tool, "description") else "",
                server=server_name,
                is_essential=not server_cfg.defer,
            )
        )
    return tools, descriptors


async def fetch_prompts(session: Any, *, server_name: str) -> list[dict]:
    """Fetch prompt descriptors from a session."""
    try:
        prompts = await session.list_prompts()
    except AttributeError:
        return []

    result: list[dict] = []
    for prompt in prompts:
        bare_name = prompt.name if hasattr(prompt, "name") else str(prompt)
        result.append(
            {
                "name": build_mcp_tool_name(server_name, bare_name),
                "bare_name": bare_name,
                "description": prompt.description if hasattr(prompt, "description") else None,
                "server": server_name,
            }
        )
    return result


async def fetch_resources(session: Any, *, server_name: str) -> list[dict]:
    """Fetch resource descriptors from a session."""
    try:
        resources = await session.list_resources()
    except AttributeError:
        return []

    result: list[dict] = []
    for resource in resources:
        result.append(
            {
                "uri": resource.uri if hasattr(resource, "uri") else str(resource),
                "name": resource.name if hasattr(resource, "name") else None,
                "description": resource.description if hasattr(resource, "description") else None,
                "server": server_name,
                "mime_type": resource.mimeType if hasattr(resource, "mimeType") else None,
            }
        )
    return result


async def cleanup_stdio_connection(registry: MCPRegistry, name: str, deadline: float) -> None:
    """Cleanup a stdio connection with the subprocess cleanup ladder."""
    conn = registry._connections.get(name)
    if not conn or not conn._session:
        return

    remaining_time = deadline - asyncio.get_event_loop().time()
    if remaining_time <= 0:
        remaining_time = 0.1

    try:
        await cleanup_subprocess(conn._session, timeout_seconds=remaining_time)
        emit_server_disconnected(name, "shutdown", was_clean=True)
    except Exception as error:  # noqa: BLE001
        logger.warning("[MCP] Cleanup ladder error for %s: %s", name, error)
        emit_server_disconnected(name, str(error), was_clean=False)


async def cleanup_remote_connection(registry: MCPRegistry, name: str) -> None:
    """Cleanup a remote connection."""
    conn = registry._connections.get(name)
    if not conn or not conn._session:
        return
    try:
        await conn._session.close()
        emit_server_disconnected(name, "shutdown", was_clean=True)
    except Exception as error:  # noqa: BLE001
        logger.warning("[MCP] Close error for %s: %s", name, error)
        emit_server_disconnected(name, str(error), was_clean=False)


async def invoke_tool(registry: MCPRegistry, server: str, tool: str, args: dict) -> Any:
    """Invoke a named MCP tool and emit telemetry events."""
    if not registry._initialized or not registry._client:
        raise RuntimeError("MCPRegistry not initialized")

    tools = registry._tools.get(server, [])
    target_tool = next((t for t in tools if t.name == tool), None)
    if not target_tool:
        raise ValueError(f"Tool {tool} not found on server {server}")

    start_time = datetime.now(UTC)
    try:
        result = await target_tool.ainvoke(args)
        latency_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
        emit_tool_invoked(
            server,
            tool,
            latency_ms,
            success=True,
            result_chars=len(str(result)),
        )
        return result
    except TimeoutError as error:
        server_cfg = next((cfg for cfg in registry._servers if cfg.name == server), None)
        timeout_s = server_cfg.tool_timeout_seconds if server_cfg else 600.0
        emit_tool_timeout(server, tool, timeout_s)
        raise RuntimeError(f"Tool {tool} timed out after {timeout_s}s") from error
    except Exception as error:  # noqa: BLE001
        latency_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
        emit_tool_invoked(server, tool, latency_ms, success=False, result_chars=0)
        raise RuntimeError(f"Tool {tool} invocation failed: {error}") from error


async def read_resource(registry: MCPRegistry, server: str, uri: str) -> str:
    """Read an MCP resource and emit telemetry."""
    if not registry._initialized or not registry._client:
        raise RuntimeError("MCPRegistry not initialized")

    start_time = datetime.now(UTC)
    try:
        blobs = await registry._client.get_resources(server_name=server, uris=uri)
        if not blobs:
            raise ValueError(f"Resource {uri} not found on server {server}")

        blob = blobs[0]
        if hasattr(blob, "data"):
            content = blob.data.decode("utf-8") if isinstance(blob.data, bytes) else str(blob.data)
        else:
            content = str(blob)

        latency_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
        emit_resource_read(server, uri, len(content), latency_ms)
        return content
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(f"Failed to read resource {uri}: {error}") from error
