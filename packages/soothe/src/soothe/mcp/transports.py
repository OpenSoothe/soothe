"""Transport factory for MCP server connections (RFC-412).

Maps MCPServerConfig to langchain_mcp_adapters connection types.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from soothe.config.models import MCPAuthHeaders, MCPServerConfig, MCPTransport


def make_connection_spec(
    server: MCPServerConfig,
    workspace: str | None = None,
) -> dict[str, Any]:
    """Map MCPServerConfig to langchain_mcp_adapters connection dict.

    Args:
        server: MCPServerConfig with resolved env vars.
        workspace: Optional cwd for stdio servers (defaults to daemon workspace).

    Returns:
        Dict matching StdioConnection, SSEConnection, StreamableHttpConnection,
        or WebsocketConnection shape (TypedDict subclasses in langchain_mcp_adapters).

    Raises:
        ValueError: If required fields are missing (should be caught by model_validator).
    """
    transport = server.transport

    if transport == MCPTransport.STDIO:
        return {
            "transport": "stdio",
            "command": server.command,
            "args": server.args,
            "env": server.env or None,
            "cwd": workspace,
        }

    if transport == MCPTransport.SSE:
        headers = _resolve_auth_headers(server.auth)
        return {
            "transport": "sse",
            "url": server.url,
            "headers": headers,
            "timeout": server.timeout_seconds,
        }

    if transport == MCPTransport.STREAMABLE_HTTP:
        headers = _resolve_auth_headers(server.auth)
        # Note: StreamableHttpConnection uses timedelta for timeout, not float
        return {
            "transport": "streamable_http",
            "url": server.url,
            "headers": headers,
            "timeout": timedelta(seconds=server.timeout_seconds),
        }

    if transport == MCPTransport.WEBSOCKET:
        return {
            "transport": "websocket",
            "url": server.url,
        }

    raise ValueError(f"Unknown transport type: {transport}")


def _resolve_auth_headers(auth: MCPAuthHeaders | None) -> dict[str, str] | None:
    """Extract headers from MCPAuthHeaders.

    Note: ${ENV_VAR} interpolation is done at MCPRegistry.initialize time
    via config.secret_resolver, not here. This function just extracts the
    pre-resolved headers dict.

    Args:
        auth: Optional MCPAuthHeaders config.

    Returns:
        Headers dict or None if no auth configured.
    """
    if auth is None:
        return None
    if not auth.headers:
        return None
    return dict(auth.headers)
