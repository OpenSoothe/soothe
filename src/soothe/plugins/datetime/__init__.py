"""DateTime plugin for date and time utilities.

This plugin provides tools for working with dates and times.
"""

from typing import Any

from soothe.tools.datetime import create_datetime_tools
from soothe_sdk import plugin


@plugin(
    name="datetime",
    version="1.0.0",
    description="Date and time utility tools",
    trust_level="built-in",
)
class DateTimePlugin:
    """DateTime plugin.

    Provides current_datetime tool.
    """

    def __init__(self) -> None:
        """Initialize datetime plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with configuration.
        """
        self._tools = create_datetime_tools()
        context.logger.info("Loaded %s datetime tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of datetime tools.
        """
        return self._tools
