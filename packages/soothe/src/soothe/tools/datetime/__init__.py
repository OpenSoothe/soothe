"""Datetime processing tools plugin.

This plugin provides Date and time utility capabilities.
"""

from typing import Any

from soothe_sdk.plugin import plugin

from .implementation import CurrentDateTimeTool, create_datetime_tools

__all__ = ["CurrentDateTimeTool", "DatetimePlugin", "create_datetime_tools"]


@plugin(
    name="datetime",
    version="1.0.0",
    description="Datetime processing tools",
    trust_level="built-in",
)
class DatetimePlugin:
    """Datetime tools plugin.

    Provides current_datetime tool.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with config and logger.
        """
        self._tools = create_datetime_tools()
        context.logger.info("Loaded %d datetime tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of datetime tool instances.
        """
        return self._tools
