"""AutopilotMonitor - proactive DAG monitoring submodule (RFC-625).

Monitors ContextEngine goal DAG, handles:
- Goal intake (fast create; LLM placement refine runs async)
- Background DAG verification (dynamic health LLM gating — IG-743)
- Post-completion verification (decomposition)
- Backoff reasoning on goal failure
- Dreaming coordination (multi-mode distillation)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from soothe.context.engine import ContextEngine
from soothe.context.models import TERMINAL_STATES
from soothe.events.internal_events import (
    INTERNAL_GOAL_COMPLETED,
    INTERNAL_GOAL_FAILED,
)

from soothe_autopilot.monitor.models import (
    GoalIntakeResult,
)
from soothe_autopilot.verify.backoff_reasoner import GoalBackoffReasoner
from soothe_autopilot.verify.goal_dag_verifier import GoalDAGVerifier

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.events.internal_bus import InternalEventBus

logger = logging.getLogger(__name__)


def _event_goal_id(event: Any) -> str | None:
    """Extract goal_id from a bus event model or dict."""
    if event is None:
        return None
    gid = getattr(event, "goal_id", None)
    if gid:
        return str(gid)
    if isinstance(event, dict):
        raw = event.get("goal_id")
        return str(raw) if raw else None
    return None


class AutopilotMonitor:
    """Proactive goal DAG monitor within AutopilotService.

    Responsibilities:
      - Goal intake: create via CE immediately; refine placement async
      - DAG verification: background loop + event triggers
      - Backoff reasoning: on goal_failed events
      - Dreaming lifecycle: emit dreaming/awake events for downstream consumers

    All mutations go through ContextEngine public APIs.
    """

    def __init__(
        self,
        ce: ContextEngine,
        bus: InternalEventBus,
        config: SootheConfig,
    ) -> None:
        """Initialize monitor with ContextEngine, event bus, and config.

        Args:
            ce: ContextEngine instance (daemon-scoped)
            bus: InternalEventBus for event routing
            config: SootheConfig with monitor settings
        """
        self._ce = ce
        self._bus = bus
        self._config = config
        self._backoff_reasoner = GoalBackoffReasoner(config)
        self._verifier = GoalDAGVerifier(ce, config)
        self._shutdown_event = asyncio.Event()
        self._placement_tasks: set[asyncio.Task[None]] = set()
        self._dag_persist: Callable[[], Awaitable[None]] | None = None
        self._suspend_notify_scan: Any = None
        self._resource_reconcile: Any = None
        self._verify_task: asyncio.Task[None] | None = None
        # Last DAG fingerprint that triggered a health LLM call.
        self._last_health_llm_fingerprint: str | None = None

        # Subscribe to internal bus topics.
        self._bus.subscribe(INTERNAL_GOAL_COMPLETED, self._on_goal_completed)
        self._bus.subscribe(INTERNAL_GOAL_FAILED, self._on_goal_failed)

    def bind_service_cancel(self, cancel_goal: Any) -> None:
        """Wire AutopilotService.cancel_goal into health/post-completion removals (IG-680)."""

        async def _cancel(goal_id: str, reason: str) -> Any:
            return await cancel_goal(goal_id, reason=reason)

        self._verifier.bind_cancel_goal(_cancel)

    def bind_dag_persist(self, persist_fn: Callable[[], Awaitable[None]]) -> None:
        """Wire AutopilotService DAG snapshot persist after async placement refine."""
        self._dag_persist = persist_fn

    async def start(self) -> None:
        """Start background verification loop."""
        self._verify_task = asyncio.create_task(self._verification_loop())
        logger.info("AutopilotMonitor started")

    async def stop(self) -> None:
        """Stop background loops and cancel in-flight placement refine tasks."""
        self._shutdown_event.set()
        for task in list(self._placement_tasks):
            task.cancel()
        if self._placement_tasks:
            await asyncio.gather(*self._placement_tasks, return_exceptions=True)
        self._placement_tasks.clear()
        if self._verify_task is not None:
            self._verify_task.cancel()
            self._verify_task = None
        logger.info("AutopilotMonitor stopped")

    # ── Goal Intake ────────────────────────────────────────────────────────

    async def intake_goal(
        self,
        description: str,
        *,
        priority: int = 50,
        workspace: str | None = None,
        depends_on: list[str] | None = None,
        source: str = "user",
        parent_id: str | None = None,
        max_retries: int | None = None,
        max_send_backs: int | None = None,
        informs: list[str] | None = None,
    ) -> GoalIntakeResult:
        """Create a goal immediately; schedule LLM placement refine in the background.

        Submit RPCs return ``goal_id`` without waiting on placement. While the
        goal is still ``pending``, refine may adjust priority / depends_on /
        informs from the placement LLM.

        Args:
            description: Goal description
            priority: Initial priority (may be adjusted async by placement)
            workspace: Optional workspace constraint
            depends_on: Optional initial dependencies
            source: Goal origin
            parent_id: Optional parent goal for hierarchical decomposition
            max_retries: Optional retry budget override
            max_send_backs: Optional consensus send-back budget override
            informs: Soft dependency goal IDs

        Returns:
            GoalIntakeResult with status and goal_id
        """
        base_deps = list(depends_on or [])
        base_informs = list(informs or [])
        goal = await self._ce.create_goal(
            description,
            priority=priority,
            parent_id=parent_id,
            max_retries=max_retries,
            max_send_backs=max_send_backs,
            depends_on=base_deps,
            informs=base_informs,
            workspace=workspace,
            source=source,
        )

        logger.info(
            "Goal intake accepted goal_id=%s source=%s priority=%s parent_id=%s "
            "deps=%d placement=pending",
            goal.id,
            source,
            priority,
            parent_id or "-",
            len(base_deps),
        )
        self._schedule_placement_refine(
            goal.id,
            description=description,
        )
        return GoalIntakeResult(
            status="accepted",
            goal_id=goal.id,
        )

    def _schedule_placement_refine(self, goal_id: str, *, description: str) -> None:
        """Fire-and-forget placement refine; no-op after shutdown."""
        if self._shutdown_event.is_set():
            return
        task = asyncio.create_task(
            self._refine_placement_async(goal_id, description=description),
            name=f"placement-refine-{goal_id[:8]}",
        )
        self._placement_tasks.add(task)

        def _done(done: asyncio.Task[None]) -> None:
            self._placement_tasks.discard(done)
            if done.cancelled():
                return
            exc = done.exception()
            if exc is not None:
                logger.error(
                    "Placement refine task crashed goal_id=%s: %s",
                    goal_id,
                    exc,
                    exc_info=exc,
                )

        task.add_done_callback(_done)

    async def _refine_placement_async(self, goal_id: str, *, description: str) -> None:
        """Apply LLM placement suggestions to a still-pending goal."""
        try:
            placement = await self._verifier.analyze_placement(description)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Placement refine LLM failed goal_id=%s", goal_id)
            return

        if self._shutdown_event.is_set():
            return

        goal = self._ce.get_goal_sync(goal_id)
        if goal is None:
            logger.info("Placement refine skipped goal_id=%s: missing", goal_id)
            return
        if goal.status != "pending":
            logger.info(
                "Placement refine skipped goal_id=%s status=%s",
                goal_id,
                goal.status,
            )
            return

        if placement.merge_with:
            logger.info(
                "Placement suggests merge with goal %s: %s",
                placement.merge_with,
                placement.reasoning,
            )

        new_priority = max(0, min(100, int(placement.adjusted_priority)))
        if new_priority != goal.priority:
            goal.priority = new_priority
            goal.touch()

        suggested_deps = [d for d in placement.suggested_dependencies if d and d != goal_id]
        final_deps = list(dict.fromkeys([*goal.depends_on, *suggested_deps]))
        if final_deps != list(goal.depends_on):
            await self._ce.update_dependencies(goal_id, final_deps)

        suggested_informs = [i for i in (placement.suggested_informs or []) if i and i != goal_id]
        if suggested_informs:
            final_informs = list(dict.fromkeys([*goal.informs, *suggested_informs]))
            if final_informs != list(goal.informs):
                goal.informs = final_informs
                goal.touch()

        logger.info(
            "Placement refine applied goal_id=%s priority=%s deps=%d informs=%d complexity=%s",
            goal_id,
            goal.priority,
            len(goal.depends_on),
            len(goal.informs),
            placement.estimated_complexity,
        )
        persist = self._dag_persist
        if persist is not None:
            try:
                await persist()
            except Exception:
                logger.warning(
                    "Placement refine persist failed goal_id=%s",
                    goal_id,
                    exc_info=True,
                )

    # ── Event Handlers ────────────────────────────────────────────────────────

    async def _on_goal_completed(self, event: Any) -> None:
        """Handle soothe.internal.goal.completed."""
        goal_id = _event_goal_id(event)
        if not goal_id:
            return

        logger.info("Goal %s completed, triggering post-completion verification", goal_id)

        # Post-completion verification
        await self._verify_post_completion(goal_id)

    async def _on_goal_failed(self, event: Any) -> None:
        """Handle soothe.internal.goal.failed."""
        goal_id = _event_goal_id(event)
        if not goal_id:
            return

        logger.warning("Goal %s failed, triggering backoff reasoning", goal_id)

        evidence_raw = getattr(event, "evidence", None)
        if evidence_raw is None and isinstance(event, dict):
            evidence_raw = event.get("evidence")

        goals = {g.id: g for g in self._ce.get_goals_by_status(None)}
        if evidence_raw is not None:
            from soothe.goal_contracts import EvidenceBundle

            if isinstance(evidence_raw, EvidenceBundle):
                evidence = evidence_raw
            elif isinstance(evidence_raw, dict):
                try:
                    evidence = EvidenceBundle.model_validate(evidence_raw)
                except Exception:
                    evidence = EvidenceBundle(
                        structured=evidence_raw if evidence_raw else {},
                        narrative=str(getattr(event, "error_message", "") or "goal failed"),
                        source="layer2_execute",
                    )
            else:
                evidence = EvidenceBundle(
                    structured={},
                    narrative=str(evidence_raw),
                    source="layer2_execute",
                )
            decision = await self._backoff_reasoner.reason_backoff(goal_id, goals, evidence)
            logger.info(
                "Backoff decision: backoff_to=%s, reason=%s",
                decision.backoff_to_goal_id,
                decision.reason,
            )
            await self._apply_backoff_decision(decision, failed_goal_id=goal_id)

    async def _apply_backoff_decision(self, decision: Any, *, failed_goal_id: str) -> None:
        """Apply backoff decision to the CE DAG (IG-678 P1-2, IG-697).

        Prefer retrying the failed goal while ``retry_count < max_retries``.
        Never transition ``failed → suspended`` (illegal in CE). When retry
        budget is exhausted, leave the goal failed for engine deadlock
        recovery on the next health cycle.
        """
        logger.info(
            "Applying backoff decision for %s → %s: %s",
            failed_goal_id,
            decision.backoff_to_goal_id,
            decision.reason,
        )
        failed = await self._ce.get_goal(failed_goal_id)
        if failed is None:
            return

        if failed.status == "failed":
            if failed.retry_count < failed.max_retries:
                try:
                    await self._ce.retry_failed_goal(failed_goal_id, reason=decision.reason)
                    return
                except ValueError:
                    logger.warning(
                        "Retry rejected for %s despite budget check; deferring to engine recovery",
                        failed_goal_id,
                    )
            logger.warning(
                "Backoff: leaving goal %s failed for engine recovery (retry %d/%d)",
                failed_goal_id,
                failed.retry_count,
                failed.max_retries,
            )
            return

        # Non-failed (e.g. already suspended elsewhere): try reactivate backoff target.
        target_id = getattr(decision, "backoff_to_goal_id", None) or failed_goal_id
        target = await self._ce.get_goal(target_id)
        if target is not None and target.status in ("suspended", "blocked"):
            await self._ce.reactivate_goal(target_id)

    # ── Background Loops ────────────────────────────────────────────────────────

    def _autopilot_cfg(self) -> Any:
        """Resolved ``agent.autopilot`` config (with safe defaults)."""
        return getattr(getattr(self._config, "agent", None), "autopilot", None)

    def _periodic_verify_enabled(self) -> bool:
        """Whether the periodic DAG health tick runs (master switch)."""
        ap = self._autopilot_cfg()
        if ap is None:
            return False
        return bool(getattr(ap, "verify_periodic_enabled", False))

    @staticmethod
    def _nonterminal_goals(goals: list[Any]) -> list[Any]:
        """Goals not in completed/failed/cancelled."""
        return [g for g in goals if getattr(g, "status", None) not in TERMINAL_STATES]

    @staticmethod
    def _health_dag_fingerprint(goals: list[Any]) -> str:
        """Stable fingerprint for health-LLM debounce.

        Includes id/status/priority/deps/informs/engine recovery so structural
        changes invalidate the debounce cache without hashing free text.
        """
        rows: list[str] = []
        for g in sorted(goals, key=lambda x: str(getattr(x, "id", ""))):
            deps = ",".join(sorted(str(d) for d in (getattr(g, "depends_on", None) or [])))
            informs = ",".join(sorted(str(i) for i in (getattr(g, "informs", None) or [])))
            rows.append(
                "|".join(
                    (
                        str(getattr(g, "id", "")),
                        str(getattr(g, "status", "")),
                        str(getattr(g, "priority", "")),
                        deps,
                        informs,
                        str(getattr(g, "engine_recovery_count", 0)),
                        str(getattr(g, "parent_id", "") or ""),
                        str(getattr(g, "rail_id", "") or ""),
                    )
                )
            )
        return "\n".join(rows)

    def _verify_tick_interval(self, *, has_open_work: bool) -> float:
        """Seconds to sleep before the next health tick."""
        ap = self._autopilot_cfg()
        active = int(getattr(ap, "verify_interval", 120) or 120) if ap is not None else 120
        if has_open_work:
            return float(active)
        idle = int(getattr(ap, "verify_idle_interval", 300) or 0) if ap is not None else 300
        if idle <= 0:
            return float(active)
        return float(idle)

    def _should_call_health_llm(self, goals: list[Any], *, fingerprint: str) -> bool:
        """Whether this tick should invoke the monitor health LLM."""
        ap = self._autopilot_cfg()
        if ap is not None and not bool(getattr(ap, "verify_llm_enabled", True)):
            return False
        min_nt = int(getattr(ap, "verify_llm_min_nonterminal", 1) or 0) if ap is not None else 1
        nonterminal = self._nonterminal_goals(goals)
        if len(nonterminal) < min_nt:
            return False
        debounce = bool(getattr(ap, "verify_llm_debounce", True)) if ap is not None else True
        if debounce and fingerprint == self._last_health_llm_fingerprint:
            return False
        return True

    async def _run_health_tick_if_enabled(self) -> bool:
        """Run one DAG health tick when the periodic master switch is on.

        Returns ``True`` when the tick ran, ``False`` when skipped because
        ``verify_periodic_enabled`` is ``False``. The watchdog tick is
        independent of this gate (see ``_verification_loop``).
        """
        if not self._periodic_verify_enabled():
            logger.debug("Periodic DAG verification disabled; skipping health tick")
            return False
        await self._run_health_tick()
        return True

    async def _run_health_tick(self) -> None:
        """One verification tick: optional LLM, then apply + watchdogs."""
        goals = self._ce.get_goals_by_status(None)
        fingerprint = self._health_dag_fingerprint(goals)
        use_llm = self._should_call_health_llm(goals, fingerprint=fingerprint)
        report = await self._verifier.verify_dag_health(use_llm=use_llm)
        if use_llm:
            self._last_health_llm_fingerprint = fingerprint
            logger.debug(
                "DAG health LLM tick goals=%d nonterminal=%d",
                len(goals),
                len(self._nonterminal_goals(goals)),
            )
        else:
            logger.debug(
                "DAG health structural tick goals=%d nonterminal=%d",
                len(goals),
                len(self._nonterminal_goals(goals)),
            )
        await self._verifier.apply_health_report(report)
        if (
            report.suggest_remove
            or report.suggest_merge
            or report.suggest_decompose
            or report.suggest_reset
        ):
            logger.info("DAG health report: %s", report.reasoning)

    async def _run_watchdog_tick(self) -> None:
        """Suspend-notify scan + resource reconcile (always, even when LLM skipped)."""
        try:
            if self._suspend_notify_scan is not None:
                await self._suspend_notify_scan()
        except Exception:
            logger.debug("Suspend notify scan failed", exc_info=True)
        try:
            if self._resource_reconcile is not None:
                count = await self._resource_reconcile()
                if count:
                    logger.info("Resource watchdog reconciled %d resource(s)", count)
        except Exception:
            logger.debug("Resource reconcile failed", exc_info=True)

    async def _verification_loop(self) -> None:
        """Background DAG health verification with dynamic LLM gating.

        When ``verify_periodic_enabled`` is ``False`` (default), the periodic
        health tick is skipped — no structural heuristics, no LLM — while the
        watchdog tick (suspend-notify scan + resource reconcile) keeps running
        on the same cadence so orphaned runtime resources are still drained.
        """
        while not self._shutdown_event.is_set():
            goals = self._ce.get_goals_by_status(None)
            has_open_work = bool(self._nonterminal_goals(goals))
            interval = self._verify_tick_interval(has_open_work=has_open_work)
            await asyncio.sleep(interval)
            if self._shutdown_event.is_set():
                break
            try:
                await self._run_health_tick_if_enabled()
            except Exception:
                logger.exception("DAG verification failed")
            await self._run_watchdog_tick()

    def bind_suspend_notify_scan(self, scan_fn: Any) -> None:
        """Wire AutopilotService.scan_notify_suspend_timeouts into the verify loop."""
        self._suspend_notify_scan = scan_fn

    def bind_resource_reconcile(self, reconcile_fn: Any) -> None:
        """Wire AutopilotService.reconcile_goal_resources into the verify loop.

        The watchdog pass catches runtime resources (spawned background
        processes, leaked worktrees) that survive past a goal's terminal
        transition due to daemon crash, silent lifecycle-hook failure, or
        race windows. It runs on the same cadence as DAG verification.
        """
        self._resource_reconcile = reconcile_fn

    async def _verify_post_completion(self, goal_id: str) -> None:
        """LLM-driven analysis after goal completion."""
        result = await self._verifier.verify_dag_post_completion(goal_id)
        await self._verifier.apply_post_completion(result)
        if result.get("new_goals") or result.get("decomposition"):
            logger.info(
                "Post-completion verification for %s: %s",
                goal_id,
                result.get("reasoning", ""),
            )
