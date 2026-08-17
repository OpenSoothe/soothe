"""Built-in cron jobs — daemon-seeded recurring maintenance tasks.

Defines a registry of built-in recurring jobs that the daemon seeds on startup
when ``cron.enable_builtin_jobs`` is true. Unlike user-submitted jobs (which go
through NL extraction), built-in jobs have deterministic schedules and
descriptions and bypass the LLM extraction path entirely.

Registry entries are keyed by a stable ``job_id`` so that re-seeding is
idempotent: if a built-in job already exists (active or otherwise), the seed
pass skips it.
"""

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


#: Registry of all built-in cron jobs. Currently empty; the daemon's
#: ``seed_builtin_jobs`` pass is a no-op until jobs are added here.
BUILTIN_JOBS: tuple[BuiltinJobSpec, ...] = ()


__all__ = [
    "BUILTIN_JOBS",
    "BuiltinJobSpec",
]
