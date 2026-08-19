"""SLA data models — breach detection, tier classification, scan results.

These models are produced by ``SlaMonitor`` and consumed by
``NotificationRouter.emit_sla_overdue`` to build ``sla.overdue``
notify intents dispatched through the existing email / webhook /
Feishu sinks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SlaTier(StrEnum):
    """Escalation tier for an overdue gap item.

    Tiers are ordered: WARNING < CRITICAL < BREACH. Each tier maps to
    a severity in the notify router:
        WARNING  → Severity.WARNING
        CRITICAL → Severity.ERROR
        BREACH   → Severity.ERROR
    """

    WARNING = "warning"
    CRITICAL = "critical"
    BREACH = "breach"

    def __ge__(self, other: SlaTier) -> bool:
        return _TIER_RANK[self] >= _TIER_RANK[other]

    def __gt__(self, other: SlaTier) -> bool:
        return _TIER_RANK[self] > _TIER_RANK[other]

    def __le__(self, other: SlaTier) -> bool:
        return _TIER_RANK[self] <= _TIER_RANK[other]

    def __lt__(self, other: SlaTier) -> bool:
        return _TIER_RANK[self] < _TIER_RANK[other]


_TIER_RANK: dict[SlaTier, int] = {
    SlaTier.WARNING: 0,
    SlaTier.CRITICAL: 1,
    SlaTier.BREACH: 2,
}


class SlaBreach(BaseModel):
    """One overdue gap item detected by the SLA monitor.

    Attributes:
        goal_id: The goal with unresolved gap items.
        job_id: The job-root goal id (same as goal_id for roots).
        tier: Escalation tier (warning / critical / breach).
        elapsed_seconds: Wall-clock seconds since the goal became active.
        threshold_seconds: The SLA threshold that was crossed.
        description: Goal description (truncated).
        workspace: Goal workspace path (if any).
        gap_summary: Compact one-line summary of remaining gaps.
        distance_from_goal: far / moderate / near / at_goal (if available).
        unresolved_components: Count of components not yet satisfied.
    """

    goal_id: str
    job_id: str
    tier: SlaTier
    elapsed_seconds: float
    threshold_seconds: float
    description: str = ""
    workspace: str | None = None
    gap_summary: str = ""
    distance_from_goal: str | None = None
    unresolved_components: int = 0


class SlaMonitorResult(BaseModel):
    """Aggregate result of one SLA monitor scan pass.

    Attributes:
        scanned: Number of active goals checked.
        breaches: Overdue gap items found (one per goal per tier crossed).
        emitted_intents: Number of notify intents actually dispatched.
        skipped_by_dedup: Number of intents suppressed by dedup.
    """

    scanned: int = 0
    breaches: list[SlaBreach] = Field(default_factory=list)
    emitted_intents: int = 0
    skipped_by_dedup: int = 0
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
