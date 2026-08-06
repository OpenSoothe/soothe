"""Timezone helpers for schedule evaluation (RFC-229 local-time cron)."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_LOCAL_SENTINEL = "local"


def resolve_schedule_timezone(name: str | None) -> tzinfo:
    """Resolve a configured schedule timezone name to a tzinfo.

    Args:
        name: ``local`` for the system timezone, ``UTC`` for UTC, or an IANA
            timezone such as ``Asia/Shanghai``.

    Returns:
        tzinfo used when interpreting cron and wall-clock schedules.

    Raises:
        ValueError: If the timezone name is invalid.
    """
    if name is None or name.upper() == "UTC":
        return UTC
    if name.casefold() == _LOCAL_SENTINEL:
        return datetime.now().astimezone().tzinfo or UTC
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        msg = f"Invalid schedule timezone: {name!r}"
        raise ValueError(msg) from exc


def schedule_timezone_label(name: str | None) -> str:
    """Return a human-readable label for prompts and logs."""
    if not name or name.casefold() == _LOCAL_SENTINEL:
        tz = resolve_schedule_timezone(name)
        return getattr(tz, "key", str(tz))
    return name


def normalize_schedule_datetime(dt: datetime, schedule_tz: tzinfo) -> datetime:
    """Normalize a schedule datetime to UTC for persistence and comparison."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=schedule_tz)
    return dt.astimezone(UTC)
