"""Local wall-clock helpers for host prompts."""

from __future__ import annotations

from datetime import UTC, datetime


def now_local() -> datetime:
    """Return current time in the system local timezone."""
    return datetime.now(UTC).astimezone()


def local_date_str() -> str:
    """Current local calendar date (YYYY-MM-DD)."""
    return now_local().strftime("%Y-%m-%d")


def local_time_str() -> str:
    """Current local wall time (HH:MM:SS)."""
    return now_local().strftime("%H:%M:%S")


def local_timezone_label() -> str:
    """IANA timezone name or fallback label for the system local zone."""
    tz = now_local().tzinfo
    if tz is None:
        return "UTC"
    return getattr(tz, "key", str(tz))


def local_timestamp_iso() -> str:
    """Current local time as ISO-8601 (includes offset)."""
    return now_local().isoformat()


def prompt_datetime_context() -> dict[str, str]:
    """Standard date/time fields for prompt templates."""
    return {
        "current_date": local_date_str(),
        "current_time": local_time_str(),
        "schedule_timezone": local_timezone_label(),
    }
