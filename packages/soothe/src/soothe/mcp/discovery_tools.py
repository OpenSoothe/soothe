"""Model-facing MCP tool discovery stub (RFC-412)."""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class SearchMcpToolsInput(BaseModel):
    """Input schema for search_mcp_tools."""

    query: str = Field(
        description="Substring to match deferred MCP tool names, servers, or descriptions"
    )
    limit: int = Field(default=10, ge=1, le=50, description="Maximum matches to return")


def create_search_mcp_tools_tool() -> StructuredTool:
    """Return search_mcp_tools stub; discovery is handled by MCPActivationMiddleware."""

    def _search_mcp_tools(query: str, limit: int = 10) -> str:
        return (
            "search_mcp_tools is handled by MCPActivationMiddleware. "
            f"Query={query!r} limit={limit}."
        )

    return StructuredTool.from_function(
        func=_search_mcp_tools,
        name="search_mcp_tools",
        description=(
            "Search deferred MCP tools by server name, tool name, or description. "
            "Returns matches and promotes them for subsequent model hops. "
            "Use exact mangled names (mcp__server__tool) when calling."
        ),
        args_schema=SearchMcpToolsInput,
    )
