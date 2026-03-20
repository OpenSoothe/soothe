"""Unified web search and content extraction tool.

Consolidates websearch capabilities (RFC-0014) with dynamic backend selection:
- Search: wizsearch (default) or serper (when SERPER_API_KEY available)
- Crawl: wizsearch_crawl (default) or jina (when JINA_API_KEY available)

The tool automatically chooses the best available backend and falls back to wizsearch.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

from soothe.utils.tool_error_handler import tool_error_handler


class WebSearchTool(BaseTool):
    """Unified web search with dynamic backend selection.

    Automatically uses serper when SERPER_API_KEY is available, otherwise wizsearch.
    Use ``research`` for deep multi-source investigation.
    """

    name: str = "websearch"
    description: str = (
        "Quick web search for factual queries, news, and current events. "
        "Returns search results with titles, URLs, and snippets. "
        "Use the `research` tool instead when a topic requires thorough "
        "investigation across multiple sources. "
        "Inputs: `query` (required), `max_results_per_engine` (default 10)."
    )

    config: dict[str, Any] = Field(default_factory=dict)
    _serper_available: bool | None = None

    def _check_serper_available(self) -> bool:
        """Check if Serper API key is available."""
        if self._serper_available is None:
            self._serper_available = bool(os.environ.get("SERPER_API_KEY", ""))
        return self._serper_available

    def _get_search_backend(self) -> BaseTool:
        """Get the appropriate search backend.

        Returns Serper if API key is available, otherwise wizsearch.
        """
        if self._check_serper_available():
            from soothe.tools._internal.serper import SerperSearchTool

            return SerperSearchTool()

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

        # Serper uses different parameters
        if self._check_serper_available():
            return backend._run(query=query, num=max_results_per_engine or 10)

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

        # Serper uses different parameters
        if self._check_serper_available():
            return await backend._arun(query=query, num=max_results_per_engine or 10)

        return await backend._arun(
            query=query,
            max_results_per_engine=max_results_per_engine,
            timeout_seconds=timeout_seconds,
        )


class WebCrawlTool(BaseTool):
    """Web content extraction with dynamic backend selection.

    Automatically uses Jina when JINA_API_KEY is available, otherwise wizsearch crawler.
    """

    name: str = "websearch_crawl"
    description: str = (
        "Extract clean, readable content from a web page URL. "
        "Returns the main text content stripped of navigation, ads, and boilerplate. "
        "Useful for reading articles, documentation, and web pages. "
        "Input: `url` (required)."
    )

    config: dict[str, Any] = Field(default_factory=dict)
    _jina_available: bool | None = None

    def _check_jina_available(self) -> bool:
        """Check if Jina API key is available."""
        if self._jina_available is None:
            self._jina_available = bool(os.environ.get("JINA_API_KEY", ""))
        return self._jina_available

    def _get_crawl_backend(self) -> BaseTool:
        """Get the appropriate crawl backend.

        Returns Jina if API key is available, otherwise wizsearch crawler.
        """
        if self._check_jina_available():
            from soothe.tools._internal.jina import JinaReaderTool

            return JinaReaderTool()

        from soothe.tools._internal.wizsearch.crawl import WizsearchCrawlPageTool

        return WizsearchCrawlPageTool()

    @tool_error_handler("websearch_crawl", return_type="str")
    def _run(self, url: str) -> str:
        """Extract content from a web page.

        Args:
            url: URL to crawl.

        Returns:
            Extracted text content.
        """
        return self._get_crawl_backend()._run(url=url)

    @tool_error_handler("websearch_crawl", return_type="str")
    async def _arun(self, url: str) -> str:
        """Async web crawl."""
        return await self._get_crawl_backend()._arun(url=url)


def create_websearch_tools(config: dict[str, Any] | None = None) -> list[BaseTool]:
    """Create unified websearch tools with dynamic backend selection.

    Args:
        config: Optional wizsearch config dict (used when wizsearch is the backend).

    Returns:
        List containing WebSearchTool and WebCrawlTool.
    """
    return [
        WebSearchTool(config=config or {}),
        WebCrawlTool(config=config or {}),
    ]
