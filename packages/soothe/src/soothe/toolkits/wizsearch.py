"""Wizsearch toolkit -- enhanced multi-engine search and headless crawl.

Provides advanced web search and crawl capabilities beyond deepagents' basic web_search/fetch_url:
- wizsearch_search: Multi-engine search (tavily, duckduckgo, brave, etc.)
- wizsearch_crawl: Headless browser crawl via wizsearch PageCrawler

Tool names are prefixed with `wizsearch_` to avoid collision with deepagents' tools.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field
from soothe_sdk.plugin import plugin

from soothe.toolkits._internal.wizsearch._crawl_impl import perform_wizsearch_crawl
from soothe.toolkits._internal.wizsearch._helpers import _run_coro
from soothe.toolkits._internal.wizsearch._search_impl import perform_wizsearch_search
from soothe.utils.tool_error_handler import tool_error_handler

logger = logging.getLogger(__name__)


class WizsearchSearchTool(BaseTool):
    """Multi-engine web search powered by wizsearch.

    Uses engines configured via wizsearch.default_engines in config.yml.
    Common engines: tavily, duckduckgo, serper, googleai, brave, bing.
    Use `research` for deep multi-source investigation.

    name: str = "wizsearch_search"
    """

    name: str = "wizsearch_search"
    description: str = (
        "Search the web using multiple engines (tavily, duckduckgo, brave, etc.). "
        "For time-sensitive queries (e.g., 'latest news', 'recent events'), "
        "first use the current_datetime tool to know today's date, then include appropriate "
        "time qualifiers (year, month) in your search query to get the most recent results. "
        "Inputs: `query` (required), `max_results_per_engine` (default: 10), "
        "`timeout_seconds` (default: 30). "
        "Returns a text summary of search results with titles, URLs, and content snippets. "
        "Use these results to compose your answer; do NOT echo the raw results to the user."
    )

    default_max_results_per_engine: int = Field(default=10)
    default_timeout: int = Field(default=30)
    default_engines: list[str] = Field(default_factory=lambda: ["tavily", "duckduckgo"])
    config: dict[str, Any] = Field(default_factory=dict)
    debug_mode: bool = False

    def __init__(self, **data: Any) -> None:
        """Initialize wizsearch search tool with optional config override.

        Args:
            **data: Tool configuration, including 'config' dict with
                'default_engines', 'max_results_per_engine', 'timeout', 'debug'.
        """
        super().__init__(**data)
        if self.config:
            if "default_engines" in self.config:
                self.default_engines = self.config["default_engines"]
            if "max_results_per_engine" in self.config:
                self.default_max_results_per_engine = self.config["max_results_per_engine"]
            if "timeout" in self.config:
                self.default_timeout = self.config["timeout"]
            self.debug_mode = self.config.get("debug", False)

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
        return _run_coro(
            perform_wizsearch_search(
                query=query,
                max_results_per_engine=max_results_per_engine
                or self.default_max_results_per_engine,
                timeout_seconds=timeout_seconds or self.default_timeout,
                engines=self.default_engines,
                debug_mode=self.debug_mode,
            )
        )

    async def _arun(
        self,
        query: str,
        max_results_per_engine: int | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        """Async web search.

        Args:
            query: Search query.
            max_results_per_engine: Max results per engine.
            timeout_seconds: Request timeout.

        Returns:
            Formatted search results.
        """
        return await perform_wizsearch_search(
            query=query,
            max_results_per_engine=max_results_per_engine or self.default_max_results_per_engine,
            timeout_seconds=timeout_seconds or self.default_timeout,
            engines=self.default_engines,
            debug_mode=self.debug_mode,
        )


class WizsearchCrawlTool(BaseTool):
    """Web content extraction using headless browser crawl.

    Uses wizsearch PageCrawler for JavaScript-rendered content extraction.
    Returns clean, readable content stripped of navigation, ads, and boilerplate.

    name: str = "wizsearch_crawl"
    """

    name: str = "wizsearch_crawl"
    description: str = (
        "Extract clean, readable content from a web page URL using headless browser. "
        "Returns the main text content stripped of navigation, ads, and boilerplate. "
        "Useful for reading articles, documentation, and web pages. "
        "Inputs: `url` (required), `content_format` ('markdown', 'html', 'text'), "
        "`only_text` (default: false)."
    )

    default_content_format: str = Field(default="markdown")
    config: dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data: Any) -> None:
        """Initialize wizsearch crawl tool.

        Args:
            **data: Tool configuration.
        """
        super().__init__(**data)

    @tool_error_handler("wizsearch_crawl", return_type="str")
    def _run(
        self,
        url: str,
        content_format: str | None = None,
        *,
        only_text: bool = False,
    ) -> str:
        """Extract content from a web page.

        Args:
            url: URL to crawl.
            content_format: Output format ('markdown', 'html', 'text').
            only_text: Extract only text content.

        Returns:
            Extracted text content.
        """
        # Wizsearch crawler returns structured dict
        result = _run_coro(
            perform_wizsearch_crawl(
                url=url,
                content_format=content_format or self.default_content_format,
                only_text=only_text,
            )
        )

        # Return content or error message
        if isinstance(result, dict):
            content = result.get("content", "")
            error = result.get("error")
            if error:
                return f"Crawl error: {error}"
            return content or "No content extracted"

        return str(result)

    @tool_error_handler("wizsearch_crawl", return_type="str")
    async def _arun(
        self,
        url: str,
        content_format: str | None = None,
        *,
        only_text: bool = False,
    ) -> str:
        """Async web crawl.

        Args:
            url: URL to crawl.
            content_format: Output format ('markdown', 'html', 'text').
            only_text: Extract only text content.

        Returns:
            Extracted text content.
        """
        # Wizsearch crawler returns structured dict
        result = await perform_wizsearch_crawl(
            url=url,
            content_format=content_format or self.default_content_format,
            only_text=only_text,
        )

        # Return content or error message
        if isinstance(result, dict):
            content = result.get("content", "")
            error = result.get("error")
            if error:
                return f"Crawl error: {error}"
            return content or "No content extracted"

        return str(result)


class WizsearchToolkit:
    """Toolkit for wizsearch-enhanced web search and crawl.

    Provides: wizsearch_search, wizsearch_crawl
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the toolkit.

        Args:
            config: Optional config dict with 'default_engines', etc.
        """
        self._config = config or {}

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List containing WizsearchSearchTool and WizsearchCrawlTool.
        """
        return [
            WizsearchSearchTool(config=self._config),
            WizsearchCrawlTool(config=self._config),
        ]


@plugin(
    name="wizsearch",
    version="1.0.0",
    description="Enhanced multi-engine search and headless crawl toolkit",
    trust_level="built-in",
)
class WizsearchPlugin:
    """Wizsearch tools plugin.

    Provides wizsearch_search and wizsearch_crawl tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with config and logger.
        """
        # Extract wizsearch config from context
        config = getattr(context, "config", {})
        wizsearch_config = config.get("wizsearch", {})

        toolkit = WizsearchToolkit(config=wizsearch_config)
        self._tools = toolkit.get_tools()

        context.logger.info(
            "Loaded %d wizsearch tools (engines=%s)",
            len(self._tools),
            wizsearch_config.get("default_engines", ["tavily", "duckduckgo"]),
        )

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of wizsearch tool instances.
        """
        return self._tools
