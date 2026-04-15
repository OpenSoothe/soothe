"""Web search tool package."""

from typing import Any

from soothe_sdk import plugin

from .implementation import CrawlWebTool, SearchWebTool, create_websearch_tools

__all__ = [
    "CrawlWebTool",
    "SearchWebTool",
    "WebsearchPlugin",
    "create_websearch_tools",
]


@plugin(
    name="web_search",
    version="1.0.0",
    description="Web search and content extraction tools",
    trust_level="built-in",
)
class WebsearchPlugin:
    """Web search tools plugin.

    Provides search_web and crawl_web tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize web search tools.

        Args:
            context: Plugin context with config and logger.
        """
        self._tools = create_websearch_tools()
        context.logger.info("Loaded %d web_search tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of web search tool instances.
        """
        return self._tools
