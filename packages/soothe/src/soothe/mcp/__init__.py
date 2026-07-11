"""MCP Management package (RFC-412).

Provides daemon-singleton MCP subsystem with:
- Per-server connection sharing via langchain_mcp_adapters.MultiServerMCPClient
- Progressive tool surfacing via MCPActivationMiddleware
- MCP prompts as slash commands (mcp__<server>__<prompt>)
- MCP resources as @server:uri attachments
"""

from soothe.mcp.budget import format_mcp_tools_within_budget
from soothe.mcp.builtin_servers import (
    builtin_mcp_server_names,
    get_builtin_mcp_server,
    get_builtin_mcp_servers,
    resolve_mcp_builtins,
)
from soothe.mcp.name_utils import build_mcp_tool_name, parse_mcp_tool_name

__all__ = [
    "build_mcp_tool_name",
    "builtin_mcp_server_names",
    "format_mcp_tools_within_budget",
    "get_builtin_mcp_server",
    "get_builtin_mcp_servers",
    "parse_mcp_tool_name",
    "resolve_mcp_builtins",
]
