"""RFC-204: Scheduler Service for time-based task execution.

Supports delayed execution (``--delay``), specific time (``--at``),
simple recurrence (``--every``), and cron expressions (``--cron``).

Scheduled tasks feed goals to GoalEngine when their time arrives.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from soothe_daemon.utils.text_preview import preview_first

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """A task waiting for its scheduled time."""

    id: str
    description: str
    schedule: ScheduleSpec
    priority: int = 50
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    next_run: datetime | None = None
    status: str = "pending"  # pending, due, running, completed, failed, cancelled

    def __post_init__(self) -> None:
        """Compute next run time if not already set."""
        if self.next_run is None:
            self.next_run = self.schedule.next_after(datetime.now(tz=UTC))


@dataclass
class ScheduleSpec:
    """Defines when a task should run."""

    kind: str  # "once", "delay", "at", "every", "cron"
    value: str  # e.g., "2h", "2026-04-04T09:00", "1h", "0 9 * * *"

    def next_after(self, after: datetime) -> datetime | None:
        """Calculate next run time after the given time.

        Args:
            after: Reference time.

        Returns:
            Next scheduled time, or None if one-shot already past.
        """
        if self.kind == "once":
            t = self._parse_datetime(self.value)
            return t if t > after else None
        if self.kind == "delay":
            delta = _parse_duration(self.value)
            return after + delta
        if self.kind == "at":
            t = self._parse_datetime(self.value)
            return t if t > after else None
        if self.kind == "every":
            delta = _parse_duration(self.value)
            if after.tzinfo is None:
                after = after.replace(tzinfo=UTC)
            elapsed = after.timestamp() % delta.total_seconds()
            return after + timedelta(seconds=delta.total_seconds() - elapsed)
        if self.kind == "cron":
            return _next_cron(self.value, after)
        return None

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        """Parse ISO 8601 datetime string."""
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt


class SchedulerService:
    """Manages scheduled tasks, feeding goals to GoalEngine.

    Args:
        persist_path: Path to persistence file for surviving restarts.
    """

    def __init__(self, persist_path: str | Path | None = None) -> None:
        """Initialize scheduler.

        Args:
            persist_path: Optional path to persistence file.
        """
        self._tasks: dict[str, ScheduledTask] = {}
        self._persist_path = Path(persist_path) if persist_path else None
        self._load_persisted()

    async def add_task(
        self,
        description: str,
        *,
        schedule_kind: str,
        schedule_value: str,
        priority: int = 50,
        task_id: str | None = None,
    ) -> ScheduledTask:
        """Add a scheduled task.

        Args:
            description: Task/goal description.
            schedule_kind: One of "once", "delay", "at", "every", "cron".
            schedule_value: Time/duration/cron string.
            priority: Goal priority.
            task_id: Override default ID.

        Returns:
            The created ScheduledTask.
        """
        import uuid

        tid = task_id or uuid.uuid4().hex[:8]
        spec = ScheduleSpec(kind=schedule_kind, value=schedule_value)
        task = ScheduledTask(
            id=tid,
            description=description,
            schedule=spec,
            priority=priority,
        )
        self._tasks[tid] = task
        logger.info(
            "Scheduled task %s: %s (%s=%s)",
            tid,
            preview_first(description, 50),
            schedule_kind,
            schedule_value,
        )
        self._save_persisted()
        return task

    def get_due_tasks(self, now: datetime | None = None) -> list[ScheduledTask]:
        """Get tasks that are due for execution.

        Args:
            now: Current time. Defaults to now.

        Returns:
            List of due tasks, ordered by next_run then creation time.
        """
        now = now or datetime.now(tz=UTC)
        due = []
        for task in self._tasks.values():
            if task.status != "pending":
                continue
            if task.next_run and task.next_run <= now:
                due.append(task)
        due.sort(key=lambda t: (t.next_run or datetime.max.replace(tzinfo=UTC), t.created_at))
        return due

    def mark_running(self, task_id: str) -> None:
        """Mark a task as running.

        Args:
            task_id: Task to mark.
        """
        task = self._tasks.get(task_id)
        if task:
            task.status = "running"

    def mark_completed(self, task_id: str) -> None:
        """Mark a one-shot task as completed.

        Args:
            task_id: Task to mark.
        """
        task = self._tasks.get(task_id)
        if task:
            task.status = "completed"

    def schedule_next(self, task_id: str) -> None:
        """Reschedule a recurring task for its next run.

        Args:
            task_id: Task to reschedule.
        """
        task = self._tasks.get(task_id)
        if task:
            now = datetime.now(tz=UTC)
            task.next_run = task.schedule.next_after(now)
            if task.next_run:
                task.status = "pending"
                logger.info("Rescheduled task %s for %s", task_id, task.next_run.isoformat())
            else:
                task.status = "completed"
                logger.info("Task %s completed (no more runs)", task_id)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a scheduled task.

        Args:
            task_id: Task to cancel.

        Returns:
            True if task was found and cancelled.
        """
        task = self._tasks.get(task_id)
        if task:
            task.status = "cancelled"
            return True
        return False

    def list_tasks(self) -> list[dict[str, Any]]:
        """List all scheduled tasks.

        Returns:
            List of task info dicts.
        """
        return [
            {
                "id": t.id,
                "description": t.description,
                "schedule_kind": t.schedule.kind,
                "schedule_value": t.schedule.value,
                "priority": t.priority,
                "status": t.status,
                "next_run": t.next_run.isoformat() if t.next_run else None,
            }
            for t in self._tasks.values()
        ]

    def _load_persisted(self) -> None:
        """Load tasks from persisted state."""
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            import json

            data = json.loads(self._persist_path.read_text())
            for item in data.get("tasks", []):
                spec = ScheduleSpec(kind=item["schedule_kind"], value=item["schedule_value"])
                task = ScheduledTask(
                    id=item["id"],
                    description=item["description"],
                    schedule=spec,
                    priority=item.get("priority", 50),
                    created_at=datetime.fromisoformat(item["created_at"]),
                    next_run=datetime.fromisoformat(item["next_run"])
                    if item.get("next_run")
                    else None,
                    status=item.get("status", "pending"),
                )
                self._tasks[task.id] = task
            logger.info("Restored %d scheduled tasks", len(self._tasks))
        except Exception:
            logger.debug("Failed to load persisted scheduler state", exc_info=True)

    def _save_persisted(self) -> None:
        """Save tasks to persisted state."""
        if not self._persist_path:
            return
        try:
            import json

            data = {
                "tasks": [
                    {
                        "id": t.id,
                        "description": t.description,
                        "schedule_kind": t.schedule.kind,
                        "schedule_value": t.schedule.value,
                        "priority": t.priority,
                        "status": t.status,
                        "created_at": t.created_at.isoformat(),
                        "next_run": t.next_run.isoformat() if t.next_run else None,
                    }
                    for t in self._tasks.values()
                ]
            }
            self._persist_path.write_text(json.dumps(data, indent=2))
        except Exception:
            logger.debug("Failed to persist scheduler state", exc_info=True)


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


def _next_cron(expr: str, after: datetime) -> datetime | None:
    """Calculate the next time matching a cron expression.

    Supports: specific values, wildcards (``*``), ranges (``1-5``),
    steps (``*/5``), and lists (``1,3,5``).

    Args:
        expr: Cron expression (5 fields).
        after: Time to search after.

    Returns:
        Next matching datetime.
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

    # Brute-force search from next minute (max ~1 year ahead)
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(525960):  # ~1 year in minutes
        if _matches_constraints(candidate, constraints):
            return candidate
        candidate += timedelta(minutes=1)
    logger.warning("No cron match found within 1 year for: %s", expr)
    return None


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
