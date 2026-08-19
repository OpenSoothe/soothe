"""Host NotificationRouter — job-root intents to injected dispatcher (IG-713)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe_autopilot.notify.dedup import NotifyDedupStore
from soothe_autopilot.notify.models import (
    NotifyIntent,
    NotifyKind,
    Severity,
)
from soothe_autopilot.notify.progress import format_progress_plain
from soothe_autopilot.sla.models import SlaBreach, SlaTier

if TYPE_CHECKING:
    from soothe.config.models import AutopilotNotifyConfig
    from soothe.context.models import GoalNode
    from soothe_sdk.protocols.persistence import AsyncPersistStore

logger = logging.getLogger(__name__)

NotifyDispatchFn = Callable[[NotifyIntent], Awaitable[None]]


def _severity_for(
    kind: NotifyKind,
    goal: GoalNode,
    *,
    progress: dict[str, Any] | None = None,
    suspended_for_seconds: float | None = None,
    suspend_threshold: float = 2700.0,
    suspend_escalation_multiplier: float = 2.0,
) -> Severity:
    """Drift-aware severity classification for a job-root intent.

    Baseline mapping (kind → severity):
        job.completed          → info
        job.suspended_timeout  → warning
        job.failed             → error

    Escalation signals (job is *drifting* away from a healthy outcome):
    - Completed job with failed/active children → warning (drift from
      a clean completion; the job nominally finished but left churn).
    - Maturity ``blockers`` present → warning (acceptance not met).
    - Suspended timeout with very long age (≥ 2× threshold) → error.
    """
    if kind == "job.failed":
        return Severity.ERROR
    if kind == "job.suspended_timeout":
        # Escalate to error when the job has been suspended for an
        # abnormally long time (beyond 2× the configured threshold),
        # signalling drift past the expected suspend window.
        if suspended_for_seconds is not None:
            if suspended_for_seconds > suspend_escalation_multiplier * suspend_threshold:
                return Severity.ERROR
        return Severity.WARNING

    # job.completed — baseline info, but escalate to warning when the
    # completion is "drifting": child failures or maturity blockers
    # indicate the job finished but not cleanly.
    severity = Severity.INFO

    # Progress drift: completed root with failed/active children.
    if progress:
        failed = int(progress.get("failed_goals") or 0)
        active = int(progress.get("active_goals") or 0)
        if failed > 0 or active > 0:
            severity = Severity.WARNING

    # Maturity drift: acceptance not met or blockers listed.
    maturity = goal.maturity if isinstance(goal.maturity, dict) else None
    if maturity:
        blockers = maturity.get("blockers") or []
        if blockers:
            severity = Severity.WARNING
        elif maturity.get("acceptance_met") is False:
            severity = Severity.WARNING

    return severity


def _title_for(
    kind: NotifyKind,
    job_id: str,
    *,
    progress: dict[str, Any] | None = None,
) -> str:
    labels = {
        "job.completed": "completed",
        "job.failed": "failed",
        "job.suspended_timeout": "suspended (timeout)",
    }
    short = job_id[:8]
    title = f"[Soothe] Job {short} {labels.get(kind, kind)}"
    if progress and int(progress.get("total_goals") or 0) > 0:
        completed = int(progress.get("completed_goals") or 0)
        total = int(progress.get("total_goals") or 0)
        title = f"{title} ({completed}/{total})"
    return title


def _body_for(
    kind: NotifyKind,
    goal: GoalNode,
    *,
    suspended_for_seconds: float | None = None,
    progress: dict[str, Any] | None = None,
) -> str:
    lines = [
        f"Job: {goal.id}",
        f"Status: {goal.status}",
    ]
    desc = (goal.description or "").strip()
    if desc:
        lines.append(f"Description: {desc[:500]}")
    if goal.workspace:
        lines.append(f"Workspace: {goal.workspace}")
    if kind == "job.failed" and goal.error:
        lines.append(f"Error: {str(goal.error)[:500]}")
    if suspended_for_seconds is not None:
        mins = int(suspended_for_seconds // 60)
        lines.append(f"Suspended for: {mins} minutes ({int(suspended_for_seconds)}s)")
    maturity = goal.maturity if isinstance(goal.maturity, dict) else None
    if maturity:
        if "acceptance_met" in maturity:
            lines.append(f"Acceptance met: {maturity.get('acceptance_met')}")
        if maturity.get("level"):
            lines.append(f"Maturity: {maturity.get('level')}")
        blockers = maturity.get("blockers") or []
        if blockers:
            lines.append(f"Blockers: {', '.join(str(b) for b in blockers[:5])}")
    progress_lines = format_progress_plain(progress)
    if progress_lines:
        lines.append("")
        lines.extend(progress_lines)
    lines.append("")
    lines.append(f"Inspect: soothe autopilot job {goal.id}")
    return "\n".join(lines)


class NotificationRouter:
    """Filter job-root lifecycle changes into NotifyIntent and dispatch.

    The daemon injects ``dispatch_fn`` (NotifyDispatcher.dispatch). When unset,
    intents are logged and dropped (tests / host-only mode).
    """

    def __init__(
        self,
        notify_config: AutopilotNotifyConfig,
        *,
        persist_store: AsyncPersistStore | None = None,
        dispatch_fn: NotifyDispatchFn | None = None,
    ) -> None:
        self._config = notify_config
        self._dedup = NotifyDedupStore(
            persist_store,
            ttl_seconds=int(self._config.dedup_ttl_seconds),
        )
        self._dispatch_fn = dispatch_fn

    def set_dispatch_fn(self, dispatch_fn: NotifyDispatchFn | None) -> None:
        """Inject or replace the daemon dispatcher callback."""
        self._dispatch_fn = dispatch_fn

    def _event_enabled(self, kind: NotifyKind) -> bool:
        return self._config.events.is_enabled(kind)

    async def emit_job_intent(
        self,
        kind: NotifyKind,
        goal: GoalNode,
        *,
        generation: str | None = None,
        suspended_for_seconds: float | None = None,
        progress: dict[str, Any] | None = None,
    ) -> NotifyIntent | None:
        """Build, dedup, and dispatch one job-root intent.

        Returns:
            The intent when dispatched (or would-dispatch without sink), else None.
        """
        if not self._config.enabled:
            return None
        if goal.parent_id is not None:
            return None
        if not self._event_enabled(kind):
            return None

        gen = generation or ""
        if not gen:
            if kind == "job.suspended_timeout" and goal.suspended_at is not None:
                gen = goal.suspended_at.isoformat()
            else:
                gen = f"{kind}:{goal.status}:{goal.updated_at.isoformat()}"

        intent = NotifyIntent(
            kind=kind,
            job_id=goal.id,
            title=_title_for(kind, goal.id, progress=progress),
            body=_body_for(
                kind,
                goal,
                suspended_for_seconds=suspended_for_seconds,
                progress=progress,
            ),
            severity=_severity_for(
                kind,
                goal,
                progress=progress,
                suspended_for_seconds=suspended_for_seconds,
                suspend_threshold=float(self._config.suspend_after_seconds),
                suspend_escalation_multiplier=float(self._config.suspend_escalation_multiplier),
            ),
            status=goal.status,
            description=(goal.description or "")[:500] or None,
            workspace=goal.workspace,
            error=str(goal.error)[:500] if goal.error else None,
            suspended_for_seconds=suspended_for_seconds,
            maturity=dict(goal.maturity) if isinstance(goal.maturity, dict) else None,
            progress=progress,
            generation=gen,
        )
        key = intent.dedup_key()
        if await self._dedup.already_sent(key):
            logger.debug("Notify dedup skip %s", key)
            return None

        await self._dedup.mark_sent(key)
        if self._dispatch_fn is None:
            logger.info(
                "Notify intent (no dispatcher) kind=%s job_id=%s",
                kind,
                goal.id,
            )
            return intent
        try:
            await self._dispatch_fn(intent)
        except Exception:
            logger.exception(
                "Notify dispatch failed kind=%s job_id=%s",
                kind,
                goal.id,
            )
        return intent

    async def on_job_root_status(
        self,
        goal: GoalNode,
        *,
        progress: dict[str, Any] | None = None,
    ) -> NotifyIntent | None:
        """Map a job-root status to completed/failed intents when applicable."""
        if goal.parent_id is not None:
            return None
        if goal.status == "completed":
            return await self.emit_job_intent("job.completed", goal, progress=progress)
        if goal.status in ("failed", "cancelled"):
            return await self.emit_job_intent("job.failed", goal, progress=progress)
        return None

    async def scan_suspended_timeouts(
        self,
        roots: list[GoalNode],
        *,
        now: datetime | None = None,
        progress_by_job: dict[str, dict[str, Any] | None] | None = None,
    ) -> list[NotifyIntent]:
        """Emit suspended_timeout for roots past ``suspend_after_seconds``."""
        if not self._config.enabled or not self._event_enabled("job.suspended_timeout"):
            return []
        threshold = float(self._config.suspend_after_seconds)
        clock = now or datetime.now(UTC)
        progress_map = progress_by_job or {}
        emitted: list[NotifyIntent] = []
        for goal in roots:
            if goal.parent_id is not None or goal.status != "suspended":
                continue
            started = goal.suspended_at or goal.updated_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            age = (clock - started).total_seconds()
            if age < threshold:
                continue
            intent = await self.emit_job_intent(
                "job.suspended_timeout",
                goal,
                suspended_for_seconds=age,
                progress=progress_map.get(goal.id),
            )
            if intent is not None:
                emitted.append(intent)
        return emitted

    async def emit_sla_overdue(
        self,
        breach: SlaBreach,
        *,
        goal: GoalNode | None = None,
    ) -> NotifyIntent | None:
        """Build, dedup, and dispatch an ``sla.overdue`` escalation intent.

        Args:
            breach: The SLA breach detected by the monitor.
            goal: Optional GoalNode for body enrichment. When None, only
                breach fields are used.

        Returns:
            The intent when dispatched (or would-dispatch without sink), else None.
        """
        if not self._config.enabled:
            return None
        if not self._event_enabled("sla.overdue"):
            return None

        severity = Severity.WARNING if breach.tier == SlaTier.WARNING else Severity.ERROR

        tier_label = breach.tier.value.upper()
        short = breach.goal_id[:8]
        title = f"[Soothe] SLA {tier_label}: goal {short} overdue ({int(breach.elapsed_seconds // 60)}m)"

        lines = [
            f"Goal: {breach.goal_id}",
            f"SLA tier: {tier_label}",
            f"Elapsed: {int(breach.elapsed_seconds // 60)} minutes ({int(breach.elapsed_seconds)}s)",
            f"Threshold: {int(breach.threshold_seconds // 60)} minutes ({int(breach.threshold_seconds)}s)",
        ]
        if goal is not None:
            lines.append(f"Status: {goal.status}")
            desc = (goal.description or "").strip()
            if desc:
                lines.append(f"Description: {desc[:500]}")
            if goal.workspace:
                lines.append(f"Workspace: {goal.workspace}")
        if breach.distance_from_goal:
            lines.append(f"Distance from goal: {breach.distance_from_goal}")
        if breach.unresolved_components:
            lines.append(f"Unresolved components: {breach.unresolved_components}")
        if breach.gap_summary:
            lines.append(f"Gaps: {breach.gap_summary}")
        lines.append("")
        lines.append(f"Inspect: soothe autopilot job {breach.goal_id}")
        body = "\n".join(lines)

        # Dedup key: one alert per goal+tier per TTL window.
        gen = f"{breach.goal_id}:{breach.tier.value}"
        intent = NotifyIntent(
            kind="sla.overdue",
            job_id=breach.goal_id,
            title=title,
            body=body,
            severity=severity,
            status=goal.status if goal is not None else None,
            description=breach.description or None,
            workspace=breach.workspace,
            metadata={
                "sla_tier": breach.tier.value,
                "elapsed_seconds": breach.elapsed_seconds,
                "threshold_seconds": breach.threshold_seconds,
                "unresolved_components": breach.unresolved_components,
                "distance_from_goal": breach.distance_from_goal,
            },
            generation=gen,
        )
        key = intent.dedup_key()
        if await self._dedup.already_sent(key):
            logger.debug("SLA notify dedup skip %s", key)
            return None

        await self._dedup.mark_sent(key)
        if self._dispatch_fn is None:
            logger.info(
                "SLA notify intent (no dispatcher) tier=%s goal_id=%s",
                breach.tier.value,
                breach.goal_id,
            )
            return intent
        try:
            await self._dispatch_fn(intent)
        except Exception:
            logger.exception(
                "SLA notify dispatch failed tier=%s goal_id=%s",
                breach.tier.value,
                breach.goal_id,
            )
        return intent
