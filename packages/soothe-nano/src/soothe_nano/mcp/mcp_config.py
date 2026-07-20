"""MCP configuration helpers: auth, builtins, and transport mapping."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Protocol

from soothe_nano.config.models import MCPAuthHeaders, MCPServerConfig, MCPTransport


class AuthProvider(Protocol):
    """Protocol for MCP authentication providers."""

    async def headers(self) -> dict[str, str]:
        """Return headers to add to the request."""

    async def on_401(self) -> bool:
        """Handle 401 response and report whether retry should happen."""


class StaticHeadersProvider:
    """Static header auth provider."""

    def __init__(self, headers: dict[str, str]) -> None:
        self._headers = headers

    async def headers(self) -> dict[str, str]:
        return dict(self._headers)

    async def on_401(self) -> bool:
        return False


def interpolate_auth_headers(
    headers: dict[str, str],
    secret_resolver: callable,
) -> dict[str, str]:
    """Interpolate ${ENV_VAR} values in auth headers."""
    resolved: dict[str, str] = {}
    for key, value in headers.items():
        resolved[key] = secret_resolver(value)
    return resolved


def _resolve_auth_headers(auth: MCPAuthHeaders | None) -> dict[str, str] | None:
    """Extract headers from MCPAuthHeaders."""
    if auth is None or not auth.headers:
        return None
    return dict(auth.headers)


def make_connection_spec(
    server: MCPServerConfig,
    workspace: str | None = None,
) -> dict[str, Any]:
    """Map MCPServerConfig to langchain_mcp_adapters connection dict."""
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
        return {
            "transport": "sse",
            "url": server.url,
            "headers": _resolve_auth_headers(server.auth),
            "timeout": server.timeout_seconds,
        }

    if transport == MCPTransport.STREAMABLE_HTTP:
        return {
            "transport": "streamable_http",
            "url": server.url,
            "headers": _resolve_auth_headers(server.auth),
            "timeout": timedelta(seconds=server.timeout_seconds),
        }

    if transport == MCPTransport.WEBSOCKET:
        return {
            "transport": "websocket",
            "url": server.url,
        }

    raise ValueError(f"Unknown transport type: {transport}")


_BUILTIN_MCP_SERVERS: tuple[MCPServerConfig, ...] = (
    MCPServerConfig(
        name="playwright",
        command="npx",
        args=["-y", "@playwright/mcp@latest", "--headless"],
        transport=MCPTransport.STDIO,
        defer=True,
    ),
    MCPServerConfig(
        name="github",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        transport=MCPTransport.STDIO,
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"},
        defer=True,
    ),
    MCPServerConfig(
        name="slack",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-slack"],
        transport=MCPTransport.STDIO,
        env={
            "SLACK_BOT_TOKEN": "${SLACK_BOT_TOKEN}",
            "SLACK_TEAM_ID": "${SLACK_TEAM_ID}",
        },
        defer=True,
    ),
    MCPServerConfig(
        name="postgres",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-postgres"],
        transport=MCPTransport.STDIO,
        env={"POSTGRES_CONNECTION_STRING": "${POSTGRES_CONNECTION_STRING}"},
        defer=True,
    ),
    MCPServerConfig(
        name="gdrive",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-gdrive"],
        transport=MCPTransport.STDIO,
        env={
            "GDRIVE_OAUTH_PATH": "${GDRIVE_OAUTH_PATH}",
            "GDRIVE_CREDENTIALS_PATH": "${GDRIVE_CREDENTIALS_PATH}",
        },
        defer=True,
    ),
    MCPServerConfig(
        name="chrome-devtools",
        command="npx",
        args=["-y", "chrome-devtools-mcp@latest"],
        transport=MCPTransport.STDIO,
        defer=True,
    ),
)


def get_builtin_mcp_servers() -> list[MCPServerConfig]:
    """Return curated builtin MCP server configurations."""
    return [server.model_copy(deep=True) for server in _BUILTIN_MCP_SERVERS]


def get_builtin_mcp_server(name: str) -> MCPServerConfig | None:
    """Get a specific builtin MCP server by name."""
    for server in _BUILTIN_MCP_SERVERS:
        if server.name == name:
            return server.model_copy(deep=True)
    return None


def builtin_mcp_server_names() -> frozenset[str]:
    """Return the set of valid mcp_builtins names."""
    return frozenset(server.name for server in _BUILTIN_MCP_SERVERS)


def resolve_mcp_builtins(names: list[str]) -> list[MCPServerConfig]:
    """Resolve builtin server names to MCPServerConfig copies."""
    available = builtin_mcp_server_names()
    unknown = [name for name in names if name not in available]
    if unknown:
        raise ValueError(f"Unknown mcp_builtins: {unknown}. Available: {sorted(available)}")
    return [get_builtin_mcp_server(name) for name in names]  # type: ignore[misc]
