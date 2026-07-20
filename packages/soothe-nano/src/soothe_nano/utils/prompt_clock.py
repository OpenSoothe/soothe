"""Local wall-clock helpers for LLM prompts."""

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


def local_timestamp_iso() -> str:
    """Current local time as ISO-8601 (includes offset)."""
    return now_local().isoformat()


def local_timezone_label() -> str:
    """IANA timezone name or fallback label for the system local zone."""
    tz = now_local().tzinfo
    if tz is None:
        return "UTC"
    return getattr(tz, "key", str(tz))


def prompt_datetime_context() -> dict[str, str]:
    """Standard date/time fields for prompt templates."""
    return {
        "current_date": local_date_str(),
        "current_time": local_time_str(),
        "schedule_timezone": local_timezone_label(),
    }


def format_friendly_local_date() -> str:
    """Return a user-facing local date (e.g. ``July 8, 2026``)."""
    now = now_local()
    return f"{now.strftime('%B')} {now.day}, {now.year}"


def build_canonical_datetime_reply() -> str:
    """Deterministic date reply for lightweight datetime social turns."""
    return f"Today is {format_friendly_local_date()}."


def response_includes_current_local_date(text: str) -> bool:
    """Return True when text cites today's configured local calendar date."""
    stripped = text.strip()
    if not stripped:
        return False
    iso = local_date_str()
    if iso in stripped:
        return True
    now = now_local()
    friendly = f"{now.strftime('%B')} {now.day}, {now.year}"
    padded_day = now.strftime(f"%B {now.day:02d}, %Y")
    return friendly in stripped or padded_day in stripped
