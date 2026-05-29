"""MCP Management package (RFC-412).

Provides daemon-singleton MCP subsystem with:
- Per-server connection sharing via langchain_mcp_adapters.MultiServerMCPClient
- Progressive tool surfacing via MCPToolSearchMiddleware
- MCP prompts as slash commands (mcp__<server>__<prompt>)
- MCP resources as @server:uri attachments
"""

from soothe.mcp.budget import format_mcp_tools_within_budget
from soothe.mcp.builtin_servers import get_builtin_mcp_servers
from soothe.mcp.name_utils import build_mcp_tool_name, parse_mcp_tool_name

__all__ = [
    "build_mcp_tool_name",
    "parse_mcp_tool_name",
    "format_mcp_tools_within_budget",
    "get_builtin_mcp_servers",
]
