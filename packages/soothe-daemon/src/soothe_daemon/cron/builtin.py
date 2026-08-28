"""Built-in cron jobs — daemon-seeded recurring maintenance tasks."""

from __future__ import annotations

from dataclasses import dataclass

from soothe_daemon.cron.models import ScheduleKind


@dataclass(frozen=True)
class BuiltinJobSpec:
    """Specification for a daemon-seeding built-in cron job.

    Attributes:
    job_id: Stable identifier used for idempotent seeding.
    description: Imperative task description dispatched to Autopilot.
    schedule_kind: Schedule type (typically CRON for recurring maintenance).
    schedule_value: Cron expression or duration string.
    priority: Goal priority (1-100).
    """

    job_id: str
    description: str
    schedule_kind: ScheduleKind
    schedule_value: str
    priority: int = 50


#: Registry of all built-in cron jobs. Seeded on daemon startup when
#: ``cron.enable_builtin_jobs`` is true.
BUILTIN_JOBS: tuple[BuiltinJobSpec, ...] = ()


__all__ = [
    "BUILTIN_JOBS",
    "BuiltinJobSpec",
]
