"""Current date/time tool for agent time-awareness.

Provides the orchestrator LLM with the ability to query the current date,
time, day of week, and timezone -- essential for time-sensitive tasks.
"""

from __future__ import annotations

import datetime as dt

from langchain_core.tools import BaseTool


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


def create_datetime_tools() -> list[BaseTool]:
    """Create datetime tool instances.

    Returns:
        List containing the current datetime tool.
    """
    return [CurrentDateTimeTool()]
