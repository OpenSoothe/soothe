"""Data inspection plugin for analyzing files and data.

This plugin provides tools for inspecting and summarizing data files.
"""

from typing import Any

from soothe.tools.data import create_data_tools
from soothe_sdk import plugin


@plugin(
    name="data",
    version="1.0.0",
    description="Data inspection and analysis tools",
    trust_level="built-in",
)
class DataPlugin:
    """Data inspection plugin.

    Provides inspect_data, summarize_data, check_data_quality, extract_text,
    get_data_info, ask_about_file tools.
    """

    def __init__(self) -> None:
        """Initialize data plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with configuration.
        """
        self._tools = create_data_tools()
        context.logger.info("Loaded %s data tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of data inspection tools.
        """
        return self._tools
