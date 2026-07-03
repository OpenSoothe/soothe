"""AutopilotMonitor - proactive DAG monitoring submodule (RFC-625).

Monitors ContextEngine goal DAG, handles:
- Goal intake with LLM placement analysis
- Background DAG verification (health checks)
- Post-completion verification (decomposition)
- Backoff reasoning on goal failure
- Dreaming coordination (multi-mode distillation)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from soothe.foundation.autopilot.monitor.backoff_reasoner import GoalBackoffReasoner
from soothe.foundation.autopilot.monitor.goal_dag_verifier import GoalDAGVerifier
from soothe.foundation.autopilot.monitor.models import (
    DreamingContext,
    DreamingMode,
    DreamingScope,
    GoalIntakeResult,
    GoalPlacement,
    ModeSwitchResult,
)
from soothe.foundation.context.engine import ContextEngine

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.foundation.events.internal_bus import InternalEventBus

logger = logging.getLogger(__name__)


class AutopilotMonitor:
    """Proactive goal DAG monitor within AutopilotService.

    Responsibilities:
      - Goal intake: receive new goals, call CE APIs with placement analysis
      - DAG verification: background loop + event triggers
      - Backoff reasoning: on goal_failed events
      - Dreaming coordination: multi-mode memory distillation

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

        # Subscribe to events
        self._bus.subscribe("goal_completed", self._on_goal_completed)
        self._bus.subscribe("goal_failed", self._on_goal_failed)

    async def start(self) -> None:
        """Start background verification and dreaming timer loops."""
        self._verify_task = asyncio.create_task(self._verification_loop())
        self._dreaming_task = asyncio.create_task(self._dreaming_timer_loop())
        logger.info("AutopilotMonitor started")

    async def stop(self) -> None:
        """Stop background loops."""
        self._shutdown_event.set()
        if hasattr(self, "_verify_task"):
            self._verify_task.cancel()
        if hasattr(self, "_dreaming_task"):
            self._dreaming_task.cancel()
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
        source_file: str | None = None,
    ) -> GoalIntakeResult:
        """Receive new goal, call CE.create_goal() with placement analysis.

        Args:
            description: Goal description
            priority: Initial priority (may be adjusted by placement analysis)
            workspace: Optional workspace constraint
            depends_on: Optional initial dependencies
            source: Goal origin
            parent_id: Optional parent goal for hierarchical decomposition
            max_retries: Optional retry budget override
            max_send_backs: Optional consensus send-back budget override
            informs: Soft dependency goal IDs
            source_file: Optional GOAL.md path when file-sourced

        Returns:
            GoalIntakeResult with status and goal_id
        """
        # Placement analysis
        placement = await self._analyze_placement(description)

        # Merge user-provided deps with suggested deps
        final_deps = list(set(depends_on or []) | set(placement.suggested_dependencies))

        # Check for merge opportunity
        if placement.merge_with:
            # TODO: Merge with existing goal
            logger.info(
                "Placement suggests merge with goal %s: %s",
                placement.merge_with,
                placement.reasoning,
            )

        # Create via CE
        goal = await self._ce.create_goal(
            description,
            priority=placement.adjusted_priority,
            parent_id=parent_id,
            max_retries=max_retries,
            max_send_backs=max_send_backs,
            depends_on=final_deps,
            informs=informs,
            source_file=source_file,
            workspace=workspace,
            source=source,
        )

        return GoalIntakeResult(
            status="accepted",
            goal_id=goal.id,
            adjusted_priority=placement.adjusted_priority,
            suggested_dependencies=placement.suggested_dependencies,
        )

    async def _analyze_placement(self, description: str) -> GoalPlacement:
        """LLM-driven placement analysis for new goal."""
        return await self._verifier.analyze_placement(description)

    # ── Event Handlers ────────────────────────────────────────────────────────

    async def _on_goal_completed(self, event: dict[str, Any]) -> None:
        """Handle goal_completed event."""
        goal_id = event.get("goal_id")
        if not goal_id:
            return

        logger.info("Goal %s completed, triggering post-completion verification", goal_id)

        # Post-completion verification
        await self._verify_post_completion(goal_id)

        # Check if DAG complete → trigger dreaming
        if self._ce.is_dag_complete():
            await self._trigger_dreaming()

    async def _on_goal_failed(self, event: dict[str, Any]) -> None:
        """Handle goal_failed event."""
        goal_id = event.get("goal_id")
        evidence = event.get("evidence")
        if not goal_id:
            return

        logger.warning("Goal %s failed, triggering backoff reasoning", goal_id)

        # Backoff reasoning
        goals = {g.id: g for g in self._ce.get_goals_by_status(None)}
        if evidence:
            from soothe.foundation.autopilot.engine.models import EvidenceBundle

            if isinstance(evidence, EvidenceBundle):
                decision = await self._backoff_reasoner.reason_backoff(goal_id, goals, evidence)
                logger.info(
                    "Backoff decision: backoff_to=%s, reason=%s",
                    decision.backoff_to_goal_id,
                    decision.reason,
                )
                # Apply decision (reset goals, create directives)
                await self._apply_backoff_decision(decision)

    async def _apply_backoff_decision(self, decision: Any) -> None:
        """Apply backoff decision to DAG."""
        # Reset failed goal to pending for retry
        # Create new goals from directives
        # TODO: Full implementation
        logger.info("Applying backoff decision: %s", decision.reason)

    # ── Background Loops ────────────────────────────────────────────────────────

    async def _verification_loop(self) -> None:
        """Background DAG health verification."""
        interval = getattr(self._config.agent.autonomous, "verify_interval", 30)
        while not self._shutdown_event.is_set():
            await asyncio.sleep(interval)
            try:
                report = await self._verifier.verify_dag_health()
                await self._verifier.apply_health_report(report)
                if (
                    report.suggest_remove
                    or report.suggest_merge
                    or report.suggest_decompose
                    or report.suggest_reset
                ):
                    logger.info("DAG health report: %s", report.reasoning)
            except Exception:
                logger.exception("DAG verification failed")

    async def _dreaming_timer_loop(self) -> None:
        """Background dreaming timer."""
        interval = getattr(self._config.agent.autonomous, "dreaming_interval", 300)
        while not self._shutdown_event.is_set():
            await asyncio.sleep(interval)
            try:
                if self._ce.is_dag_complete():
                    await self._trigger_dreaming()
            except Exception:
                logger.exception("Dreaming timer failed")

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

    # ── Dreaming ────────────────────────────────────────────────────────────────

    async def _trigger_dreaming(
        self,
        modes: list[DreamingMode] | None = None,
        scope: DreamingScope = "loop",
    ) -> None:
        """Trigger dreaming distillation."""
        await self._bus.emit("dreaming_mode_entered", {})

        enabled_modes = modes or ["episodic", "procedure", "semantic", "profile"]
        context = await self._gather_dreaming_context(scope)

        for mode in enabled_modes:
            try:
                await self._distill_mode(mode, context)
                logger.info("Dreaming mode %s completed", mode)
            except Exception:
                logger.exception("Dreaming mode %s failed", mode)

        await self._bus.emit("dreaming_mode_exited", {})

    async def _gather_dreaming_context(self, scope: DreamingScope) -> DreamingContext:
        """Gather goals and ledger for dreaming."""
        goals = self._ce.get_goals_by_status(None)
        ledger = self._ce.get_ledger_entries()

        if scope == "loop":
            scope_id = "current_loop"
        elif scope == "workspace":
            # TODO: Aggregate across workspace
            scope_id = "workspace"
        else:
            scope_id = "topic"

        return DreamingContext(goals=goals, ledger=ledger, scope_id=scope_id)

    async def _distill_mode(self, mode: DreamingMode, context: DreamingContext) -> Any:
        """Run LLM distillation for a specific mode."""
        # TODO: LLM integration per RFC-625 spec
        logger.info("Distilling mode %s with %d goals", mode, len(context.goals))
        return None

    # ── Mode Switch ────────────────────────────────────────────────────────────────

    async def toggle_autopilot(self, loop_id: str, enable: bool) -> ModeSwitchResult:
        """Toggle autopilot mode on/off."""
        if enable:
            # Analyze existing linear chain for restructuring
            goals = self._ce.get_goals_by_status("pending")
            if len(goals) > 1:
                logger.info("Analyzing linear chain for restructuring")
            await self._bus.emit("autopilot_mode_switched", {"loop_id": loop_id, "enabled": True})
            return ModeSwitchResult(loop_id=loop_id, enabled=True)
        else:
            # Flatten pending goals to linear chain
            pending = self._ce.get_goals_by_status("pending")
            active = self._ce.get_goals_by_status("active")

            sorted_pending = sorted(pending, key=lambda g: g.created_at)
            prev_id = active[0].id if active else None

            for goal in sorted_pending:
                await self._ce.update_dependencies(goal.id, depends_on=[prev_id] if prev_id else [])
                prev_id = goal.id

            await self._bus.emit("autopilot_mode_switched", {"loop_id": loop_id, "enabled": False})
            return ModeSwitchResult(loop_id=loop_id, enabled=False)
