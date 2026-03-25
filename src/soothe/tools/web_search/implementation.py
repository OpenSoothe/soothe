"""Unified web search and content extraction tool.

Consolidates websearch capabilities (RFC-0014) with config-driven backend selection:
- Search: wizsearch with engines configured via web_search.default_engines
- Crawl: wizsearch or jina configured via web_search.crawler

All settings are controlled through config.yml for consistency.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

from soothe.utils.tool_error_handler import tool_error_handler


class SearchWebTool(BaseTool):
    """Unified web search using wizsearch with config-driven engine selection.

    Uses engines configured via web_search.default_engines in config.yml.
    Common engines: tavily, duckduckgo, serper, googleai, brave, bing.
    Use ``research`` for deep multi-source investigation.
    """

    name: str = "search_web"
    description: str = (
        "Quick web search for factual queries, news, and current events. "
        "Returns search results with titles, URLs, and snippets. "
        "Use the `research` tool instead when a topic requires thorough "
        "investigation across multiple sources. "
        "Inputs: `query` (required), `max_results_per_engine` (default 10)."
    )

    config: dict[str, Any] = Field(default_factory=dict)

    def _get_search_backend(self) -> BaseTool:
        """Get the appropriate search backend."""
        from soothe.tools._internal.wizsearch.search import WizsearchSearchTool

        return WizsearchSearchTool(config=self.config)

    def _run(
        self,
        query: str,
        max_results_per_engine: int | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        """Execute a web search.

        Args:
            query: Search query.
            max_results_per_engine: Max results per engine.
            timeout_seconds: Request timeout.

        Returns:
            Formatted search results.
        """
        backend = self._get_search_backend()
        return backend._run(
            query=query,
            max_results_per_engine=max_results_per_engine,
            timeout_seconds=timeout_seconds,
        )

    async def _arun(
        self,
        query: str,
        max_results_per_engine: int | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        """Async web search."""
        backend = self._get_search_backend()
        return await backend._arun(
            query=query,
            max_results_per_engine=max_results_per_engine,
            timeout_seconds=timeout_seconds,
        )


class CrawlWebTool(BaseTool):
    """Web content extraction using configured crawler backend.

    Uses the crawler specified in config (default: wizsearch, optional: jina).
    Set web_search.crawler in config.yml to configure.
    """

    name: str = "crawl_web"
    description: str = (
        "Extract clean, readable content from a web page URL. "
        "Returns the main text content stripped of navigation, ads, and boilerplate. "
        "Useful for reading articles, documentation, and web pages. "
        "Input: `url` (required)."
    )

    config: dict[str, Any] = Field(default_factory=dict)

    def _get_crawl_backend(self) -> BaseTool:
        """Get the appropriate crawl backend based on config.

        Returns the configured crawler (wizsearch or jina).
        """
        # Determine crawler from config or use default
        crawler = self.config.get("crawler", "wizsearch")

        if crawler == "jina":
            from soothe.tools._internal.jina import JinaReaderTool

            return JinaReaderTool()

        # Default to wizsearch crawler
        from soothe.tools._internal.wizsearch.crawl import WizsearchCrawlPageTool

        return WizsearchCrawlPageTool()

    @tool_error_handler("crawl_web", return_type="str")
    def _run(self, url: str) -> str:
        """Extract content from a web page.

        Args:
            url: URL to crawl.

        Returns:
            Extracted text content.
        """
        return self._get_crawl_backend()._run(url=url)

    @tool_error_handler("crawl_web", return_type="str")
    async def _arun(self, url: str) -> str:
        """Async web crawl."""
        return await self._get_crawl_backend()._arun(url=url)


def create_websearch_tools(config: dict[str, Any] | None = None) -> list[BaseTool]:
    """Create unified websearch tools with dynamic backend selection.

    Args:
        config: Optional wizsearch config dict (used when wizsearch is the backend).

    Returns:
        List containing SearchWebTool and CrawlWebTool.
    """
    return [
        SearchWebTool(config=config or {}),
        CrawlWebTool(config=config or {}),
    ]
