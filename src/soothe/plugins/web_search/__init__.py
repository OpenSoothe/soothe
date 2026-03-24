"""Web search plugin for searching and crawling the web.

This plugin provides tools for web search and web crawling.
"""

from typing import Any

from soothe.tools.web_search import create_websearch_tools
from soothe_sdk import plugin


@plugin(
    name="web_search",
    version="1.0.0",
    description="Web search and crawling tools",
    trust_level="built-in",
)
class WebSearchPlugin:
    """Web search plugin.

    Provides search_web and crawl_web tools.
    """

    def __init__(self) -> None:
        """Initialize web search plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools with search config.

        Args:
            context: Plugin context with configuration.
        """
        self._tools = create_websearch_tools(context.soothe_config)
        context.logger.info("Loaded %s web_search tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of web search tools.
        """
        return self._tools
