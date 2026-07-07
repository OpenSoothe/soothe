"""RFC-204: schedule math for CronService.

Supports delayed execution (``--delay``), specific time (``--at``),
simple recurrence (``--every``), and cron expressions (``--cron``).

Used by CronService for next-run calculation and schedule parsing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo

from soothe.foundation.autopilot.engine.schedule_timezone import (
    normalize_schedule_datetime,
    resolve_schedule_timezone,
)

logger = logging.getLogger(__name__)


@dataclass
class ScheduleSpec:
    """Defines when a task should run."""

    kind: str  # "once", "delay", "at", "every", "cron"
    value: str  # e.g., "2h", "2026-04-04T09:00", "1h", "0 9 * * *"
    timezone: str | None = None  # "local", "UTC", or IANA name; None => UTC

    def next_after(self, after: datetime) -> datetime | None:
        """Calculate next run time after the given time.

        Args:
            after: Reference time.

        Returns:
            Next scheduled time in UTC, or None if one-shot already past.
        """
        after_utc = _as_utc(after)
        schedule_tz = resolve_schedule_timezone(self.timezone)

        if self.kind == "once":
            t = self._parse_datetime(self.value, schedule_tz)
            return t if t > after_utc else None
        if self.kind == "delay":
            delta = _parse_duration(self.value)
            return after_utc + delta
        if self.kind == "at":
            t = self._parse_datetime(self.value, schedule_tz)
            return t if t > after_utc else None
        if self.kind == "every":
            delta = _parse_duration(self.value)
            elapsed = after_utc.timestamp() % delta.total_seconds()
            return after_utc + timedelta(seconds=delta.total_seconds() - elapsed)
        if self.kind == "cron":
            return _next_cron(self.value, after_utc, schedule_tz)
        return None

    @staticmethod
    def _parse_datetime(value: str, schedule_tz: tzinfo) -> datetime:
        """Parse ISO 8601 datetime string in the configured schedule timezone."""
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=schedule_tz)
        return normalize_schedule_datetime(dt, schedule_tz)


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(
    r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?(?:(\d+)d)?",
    re.IGNORECASE,
)


def _parse_duration(value: str) -> timedelta:
    """Parse a duration string like '2h', '30m', '1h30m', '1d'.

    Args:
        value: Duration string.

    Returns:
        Parsed timedelta.

    Raises:
        ValueError: If value cannot be parsed.
    """
    m = _DURATION_RE.fullmatch(value)
    if not m or not any(m.groups()):
        msg = f"Invalid duration: {value!r}. Use format like 2h, 30m, 1d"
        raise ValueError(msg)
    return timedelta(
        days=int(m.group(4) or 0),
        hours=int(m.group(1) or 0),
        minutes=int(m.group(2) or 0),
        seconds=int(m.group(3) or 0),
    )


# ---------------------------------------------------------------------------
# Simple cron parser (subset of cron syntax)
# ---------------------------------------------------------------------------

_CRON_FIELDS = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day_of_month": (1, 31),
    "month": (1, 12),
    "day_of_week": (0, 6),
}


def _next_cron(expr: str, after: datetime, schedule_tz: tzinfo) -> datetime | None:
    """Calculate the next UTC time matching a cron expression in ``schedule_tz``.

    Supports: specific values, wildcards (``*``), ranges (``1-5``),
    steps (``*/5``), and lists (``1,3,5``).

    Args:
        expr: Cron expression (5 fields).
        after: Reference instant (UTC-aware).
        schedule_tz: Timezone used to interpret cron wall-clock fields.

    Returns:
        Next matching datetime in UTC.
    """
    parts = expr.strip().split()
    cron_field_count = 5  # standard 5-field cron: min hour dom month dow
    if len(parts) != cron_field_count:
        logger.warning("Invalid cron expression: %s (need 5 fields)", expr)
        return None

    constraints = {}
    for name, (lo, hi) in _CRON_FIELDS.items():
        pattern = parts[list(_CRON_FIELDS).index(name)]
        values = _parse_cron_field(pattern, lo, hi)
        if not values:
            return None
        constraints[name] = values

    local_after = _as_utc(after).astimezone(schedule_tz)
    candidate = local_after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(525960):  # ~1 year in minutes
        if _matches_constraints(candidate, constraints):
            return normalize_schedule_datetime(candidate, schedule_tz)
        candidate += timedelta(minutes=1)
    logger.warning("No cron match found within 1 year for: %s", expr)
    return None


def _as_utc(dt: datetime) -> datetime:
    """Return an aware UTC datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _matches_constraints(dt: datetime, constraints: dict[str, set[int]]) -> bool:
    """Check if a datetime matches all cron constraints.

    Args:
        dt: Datetime to check.
        constraints: Dict of field name → set of valid values.

    Returns:
        True if datetime matches all constraints.
    """
    checks = {
        "minute": dt.minute,
        "hour": dt.hour,
        "day_of_month": dt.day,
        "month": dt.month,
        "day_of_week": dt.weekday(),  # Python: Mon=0; cron: Sun=0
    }
    for field_name, values in constraints.items():
        val = checks[field_name]
        # Adjust day_of_week: Python Mon=0..Sun=6, cron Sun=0..Sat=6
        if field_name == "day_of_week":
            val = (val + 1) % 7
        if val not in values:
            return False
    return True


def _parse_cron_field(pattern: str, lo: int, hi: int) -> set[int] | None:
    """Parse a single cron field into a set of valid values.

    Args:
        pattern: Cron field pattern (``*``, ``1-5``, ``*/2``, ``1,3,5``).
        lo: Minimum valid value.
        hi: Maximum valid value.

    Returns:
        Set of valid values, or None if pattern is invalid.
    """
    values: set[int] = set()
    for part in pattern.split(","):
        if part == "*":
            return set(range(lo, hi + 1))
        if part.startswith("*/"):
            try:
                step = int(part[2:])
            except ValueError:
                return None
            values.update(range(lo, hi + 1, step))
        elif "-" in part:
            try:
                a, b = map(int, part.split("-", 1))
            except ValueError:
                return None
            values.update(range(max(a, lo), min(b, hi) + 1))
        else:
            try:
                v = int(part)
                if lo <= v <= hi:
                    values.add(v)
                else:
                    return None
            except ValueError:
                return None
    return values or None
