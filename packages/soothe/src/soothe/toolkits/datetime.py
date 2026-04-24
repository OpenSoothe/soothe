"""Current date/time tool for agent time-awareness.

Provides the orchestrator LLM with the ability to query the current date,
time, day of week, and timezone -- essential for time-sensitive tasks.
"""

from __future__ import annotations

import datetime as dt

from langchain_core.tools import BaseTool
from soothe_sdk.plugin import plugin


class CurrentDateTimeTool(BaseTool):
    """Return the current date, time, day of week, and timezone."""

    name: str = "current_datetime"
    description: str = (
        "Get the current date, time, day of week, and timezone. "
        "Use when you need to know today's date or the current time."
    )

    def _run(self) -> dict[str, str]:
        return _get_current_datetime()

    async def _arun(self) -> dict[str, str]:
        return _get_current_datetime()


def _get_current_datetime() -> dict[str, str]:
    """Build the datetime payload."""
    now = dt.datetime.now(dt.UTC).astimezone()
    utc_offset = now.strftime("%z")
    tz_label = f"UTC{utc_offset[:3]}:{utc_offset[3:]}" if utc_offset else "UTC"
    return {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day": now.strftime("%A"),
        "timezone": tz_label,
        "iso": now.isoformat(),
    }


class DatetimeToolkit:
    """Toolkit for datetime operations."""

    def __init__(self) -> None:
        """Initialize the toolkit."""

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List containing the current datetime tool.
        """
        return [CurrentDateTimeTool()]


@plugin(name="datetime", version="1.0.0", description="Datetime operations", trust_level="built-in")
class DatetimePlugin:
    """Datetime tools plugin.

    Provides current_datetime tool.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with config and logger.
        """
        toolkit = DatetimeToolkit()
        self._tools = toolkit.get_tools()

        context.logger.info("Loaded %d datetime tools", len(self._tools))

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of datetime tool instances.
        """
        return self._tools
