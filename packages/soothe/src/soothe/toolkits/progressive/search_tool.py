"""Builtin search_tools for progressive tool discovery."""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class SearchToolsInput(BaseModel):
    """Input schema for search_tools."""

    query: str = Field(
        description="Substring to match against deferred tool names and descriptions"
    )
    limit: int = Field(default=10, ge=1, le=50, description="Maximum matches to return")


def create_search_tools_tool() -> StructuredTool:
    """Return the search_tools stub; promotion is handled by ProgressiveToolMiddleware."""

    def _search_tools(query: str, limit: int = 10) -> str:
        return (
            f"search_tools is handled by ProgressiveToolMiddleware. Query={query!r} limit={limit}."
        )

    return StructuredTool.from_function(
        func=_search_tools,
        name="search_tools",
        description=(
            "Search deferred tools by name or description. "
            "Returns matching tools and promotes them for subsequent model hops."
        ),
        args_schema=SearchToolsInput,
    )
