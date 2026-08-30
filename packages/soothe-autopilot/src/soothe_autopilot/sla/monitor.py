"""SLA monitor — overdue gap detection and tiered escalation.

Scans active (non-terminal) goals for unresolved gap items that have
persisted past configured SLA thresholds. Each threshold crossing
produces an `SlaBreach` which is dispatched as an `sla.overdue`
notify intent through the existing NotificationRouter → daemon sink
pipeline (email, webhook, Feishu).

The monitor is designed to run on the AutopilotMonitor watchdog tick
alongside the existing suspend-notify scan, sharing the same cadence
and dedup infrastructure.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from soothe_autopilot.sla.models import SlaBreach, SlaMonitorResult, SlaTier

if TYPE_CHECKING:
    from soothe.config.models import SlaConfig
    from soothe.context.models import GoalNode

    from soothe_autopilot.notify.router import NotificationRouter

logger = logging.getLogger(__name__)

# Active (non-terminal) goal statuses that are eligible for SLA monitoring.
_ACTIVE_STATUSES = frozenset(
    {"active", "suspended", "blocked", "pending", "awaiting_clarification"}
)


def _extract_gap_items(goal: GoalNode) -> tuple[list[str], str | None, int]:
    """Extract unresolved gap items from a goal's last gap analysis.

    Returns (remaining_gaps, distance_from_goal, unresolved_components).
    """
    gap_data = goal.last_gap_analysis
    if not isinstance(gap_data, dict):
        return [], None, 0

    remaining_gaps: list[str] = []
    raw_gaps = gap_data.get("remaining_gaps")
    if isinstance(raw_gaps, list):
        remaining_gaps = [str(g) for g in raw_gaps if g]

    distance = gap_data.get("distance_from_goal")
    distance_str = str(distance) if distance else None

    unresolved = 0
    components = gap_data.get("components")
    if isinstance(components, list):
        for comp in components:
            if isinstance(comp, dict):
                status = comp.get("status")
                if status in ("not_started", "partial", "blocked"):
                    unresolved += 1

    if unresolved == 0 and remaining_gaps:
        unresolved = len(remaining_gaps)

    return remaining_gaps, distance_str, unresolved


def _goal_elapsed_seconds(goal: GoalNode, *, now: datetime) -> float:
    """Wall-clock seconds since the goal became active (current run).

    Uses `started_at` when available (reset on retry/send-back/crash
    recovery so elapsed counts only the current run). Falls back to
    `created_at` for goals that never started (pending/awaiting).
    """
    base = goal.started_at or goal.created_at
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    return max(0.0, (now - base).total_seconds())


def _classify_tier(elapsed: float, config: SlaConfig) -> SlaTier | None:
    """Classify elapsed seconds into the highest applicable SLA tier.

    Returns None when no threshold is crossed (or all thresholds are 0).
    """
    breach = config.breach_seconds
    critical = config.critical_seconds
    warning = config.warning_seconds

    if breach > 0 and elapsed >= breach:
        return SlaTier.BREACH
    if critical > 0 and elapsed >= critical:
        return SlaTier.CRITICAL
    if warning > 0 and elapsed >= warning:
        return SlaTier.WARNING
    return None


class SlaMonitor:
    """Overdue gap detection with tiered escalation alerts.

    The monitor scans active goals, classifies each against SLA thresholds,
    and dispatches `sla.overdue` notify intents through the
    NotificationRouter. Dedup is handled at the router level (one alert
    per goal+tier per TTL window).
    """

    def __init__(
        self,
        sla_config: SlaConfig,
        router: NotificationRouter,
    ) -> None:
        self._config = sla_config
        self._router = router

    async def scan(
        self,
        goals: list[GoalNode],
        *,
        now: datetime | None = None,
    ) -> SlaMonitorResult:
        """Scan active goals for overdue gap items and dispatch alerts.

        Args:
            goals: All goals to check (typically the full DAG snapshot).
                Only non-terminal goals with unresolved gaps are evaluated.
            now: Override clock for testing.

        Returns:
            Aggregate result with breaches found and intents emitted.
        """
        if not self._config.enabled:
            return SlaMonitorResult()

        clock = now or datetime.now(UTC)
        breaches: list[SlaBreach] = []
        emitted = 0
        skipped = 0

        for goal in goals:
            if goal.status not in _ACTIVE_STATUSES:
                continue

            remaining_gaps, distance, unresolved = _extract_gap_items(goal)
            if unresolved == 0 and not remaining_gaps:
                continue  # No gaps → not overdue

            elapsed = _goal_elapsed_seconds(goal, now=clock)
            tier = _classify_tier(elapsed, self._config)
            if tier is None:
                continue  # Below all thresholds

            gap_summary = "; ".join(remaining_gaps[:3])
            if len(remaining_gaps) > 3:
                gap_summary += f" (+{len(remaining_gaps) - 3} more)"

            threshold_map = {
                SlaTier.WARNING: self._config.warning_seconds,
                SlaTier.CRITICAL: self._config.critical_seconds,
                SlaTier.BREACH: self._config.breach_seconds,
            }
            breach = SlaBreach(
                goal_id=goal.id,
                job_id=goal.id,  # Roots use their own id; children inherit root
                tier=tier,
                elapsed_seconds=elapsed,
                threshold_seconds=float(threshold_map[tier]),
                description=(goal.description or "")[:500],
                workspace=goal.workspace,
                gap_summary=gap_summary,
                distance_from_goal=distance,
                unresolved_components=unresolved,
            )
            breaches.append(breach)

            intent = await self._router.emit_sla_overdue(breach, goal=goal)
            if intent is not None:
                emitted += 1
            else:
                skipped += 1

        return SlaMonitorResult(
            scanned=len(goals),
            breaches=breaches,
            emitted_intents=emitted,
            skipped_by_dedup=skipped,
            scanned_at=clock,
        )
