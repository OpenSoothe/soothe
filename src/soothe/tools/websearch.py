"""Quick single-call web search tool.

Thin wrapper around WizsearchSearchTool, exposed as ``websearch`` for the
capability-consolidated tool surface (RFC-0014).  The original ``wizsearch``
tool group remains available for backward compatibility.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field


class WebSearchTool(BaseTool):
    """Quick web search via wizsearch (no iteration, single call).

    Use ``research`` for deep multi-source investigation.
    """

    name: str = "websearch"
    description: str = (
        "Quick web search for factual queries, news, and current events. "
        "Returns search results with titles, URLs, and snippets. "
        "Use the `research` tool instead when a topic requires thorough "
        "investigation across multiple sources. "
        "Inputs: `query` (required), `engines` (optional), "
        "`max_results_per_engine` (default 10)."
    )

    config: dict[str, Any] = Field(default_factory=dict)

    def _get_delegate(self) -> BaseTool:
        """Lazily construct the underlying WizsearchSearchTool."""
        from soothe.tools._internal.wizsearch.search import WizsearchSearchTool

        return WizsearchSearchTool(config=self.config)

    def _run(
        self,
        query: str,
        engines: list[str] | str | None = None,
        max_results_per_engine: int | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        """Execute a web search.

        Args:
            query: Search query.
            engines: Optional engine list override.
            max_results_per_engine: Max results per engine.
            timeout_seconds: Request timeout.

        Returns:
            Formatted search results.
        """
        return self._get_delegate()._run(
            query=query,
            engines=engines,
            max_results_per_engine=max_results_per_engine,
            timeout_seconds=timeout_seconds,
        )

    async def _arun(
        self,
        query: str,
        engines: list[str] | str | None = None,
        max_results_per_engine: int | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        """Async web search."""
        return await self._get_delegate()._arun(
            query=query,
            engines=engines,
            max_results_per_engine=max_results_per_engine,
            timeout_seconds=timeout_seconds,
        )


def create_websearch_tools(config: dict[str, Any] | None = None) -> list[BaseTool]:
    """Create the websearch tool.

    Args:
        config: Optional wizsearch config dict.

    Returns:
        List containing a single WebSearchTool.
    """
    return [WebSearchTool(config=config or {})]
