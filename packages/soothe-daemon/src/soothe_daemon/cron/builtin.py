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


#: Weekly historical-data refresh for the drift review dashboard.
#:
#: Runs every Monday at 03:00 local schedule time. The cron ``day_of_week=1``
#: field selects Monday (cron: Sun=0, Mon=1). The job dispatches an imperative
#: task to Autopilot that re-pulls historical run data and refreshes the
#: dashboard's underlying dataset so drift reviews operate on a current corpus.
WEEKLY_HISTORICAL_DATA_REFRESH = BuiltinJobSpec(
    job_id="builtin-weekly-historical-refresh",
    description=(
        "Refresh historical data for the drift review dashboard by re-pulling "
        "the latest run history and rebuilding the review dataset"
    ),
    schedule_kind=ScheduleKind.CRON,
    schedule_value="0 3 * * 1",
    priority=40,
)


#: Registry of all built-in cron jobs.
BUILTIN_JOBS: tuple[BuiltinJobSpec, ...] = (WEEKLY_HISTORICAL_DATA_REFRESH,)


__all__ = [
    "BUILTIN_JOBS",
    "BuiltinJobSpec",
    "WEEKLY_HISTORICAL_DATA_REFRESH",
]
