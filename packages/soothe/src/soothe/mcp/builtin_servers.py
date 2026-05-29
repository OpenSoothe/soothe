"""Builtin MCP server configurations (RFC-412).

Provides curated MCP servers that are available by default (opt-in via config).
"""

from soothe.config.models import MCPServerConfig, MCPTransport


def get_builtin_mcp_servers() -> list[MCPServerConfig]:
    """Return curated builtin MCP server configurations.

    These servers are well-maintained, commonly useful, and available via npx.
    Users can enable them by adding to their config.mcp_servers list.

    Returns:
        List of MCPServerConfig for builtin servers.
    """
    return [
        MCPServerConfig(
            name="chrome-devtools",
            command="npx",
            args=["-y", "chrome-devtools-mcp@latest"],
            transport=MCPTransport.STDIO,
            enabled=True,  # user must explicitly add to config to activate
            defer=True,  # progressive disclosure
        ),
        # Future builtins can be added here:
        # - filesystem: modelcontextprotocol/server-filesystem
        # - github: github MCP
        # - postgres: postgres MCP
    ]


def get_builtin_mcp_server(name: str) -> MCPServerConfig | None:
    """Get a specific builtin MCP server by name.

    Args:
        name: Server name to look up.

    Returns:
        MCPServerConfig if found, else None.
    """
    for server in get_builtin_mcp_servers():
        if server.name == name:
            return server
    return None
