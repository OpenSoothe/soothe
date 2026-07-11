"""Builtin MCP server configurations (RFC-412).

Curated daily-use MCP servers. They are **not** connected unless listed in
``mcp_builtins`` or copied into ``mcp_servers``. All builtins use
``defer: true`` so tools are surfaced via progressive loading
(``search_mcp_tools`` + promote), not bound on cold start.
"""

from __future__ import annotations

from soothe.config.models import MCPServerConfig, MCPTransport

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
    """Return curated builtin MCP server configurations.

    These servers are well-maintained and commonly useful. Enable by name via
    ``mcp_builtins`` in config, or copy entries into ``mcp_servers``.

    Returns:
        List of MCPServerConfig for builtin servers (all ``defer=True``).
    """
    return [server.model_copy(deep=True) for server in _BUILTIN_MCP_SERVERS]


def get_builtin_mcp_server(name: str) -> MCPServerConfig | None:
    """Get a specific builtin MCP server by name.

    Args:
        name: Server name to look up.

    Returns:
        MCPServerConfig if found, else None.
    """
    for server in _BUILTIN_MCP_SERVERS:
        if server.name == name:
            return server.model_copy(deep=True)
    return None


def builtin_mcp_server_names() -> frozenset[str]:
    """Return the set of valid ``mcp_builtins`` names."""
    return frozenset(server.name for server in _BUILTIN_MCP_SERVERS)


def resolve_mcp_builtins(names: list[str]) -> list[MCPServerConfig]:
    """Resolve builtin server names to ``MCPServerConfig`` copies.

    Args:
        names: Builtin server names (e.g. ``playwright``, ``github``).

    Returns:
        Deep copies of matching builtin configs.

    Raises:
        ValueError: If any name is unknown.
    """
    available = builtin_mcp_server_names()
    unknown = [name for name in names if name not in available]
    if unknown:
        raise ValueError(f"Unknown mcp_builtins: {unknown}. Available: {sorted(available)}")
    return [get_builtin_mcp_server(name) for name in names]  # type: ignore[misc]
