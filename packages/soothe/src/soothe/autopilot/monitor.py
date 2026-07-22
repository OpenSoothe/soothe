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

from soothe.autopilot.backoff_reasoner import GoalBackoffReasoner
from soothe.autopilot.goal_dag_verifier import GoalDAGVerifier
from soothe.autopilot.monitor_models import (
    GoalIntakeResult,
    GoalPlacement,
)
from soothe.context.engine import ContextEngine

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.events.internal_bus import InternalEventBus

logger = logging.getLogger(__name__)


class AutopilotMonitor:
    """Proactive goal DAG monitor within AutopilotService.

    Responsibilities:
      - Goal intake: receive new goals, call CE APIs with placement analysis
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
            from soothe.autopilot.engine_models import EvidenceBundle

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
        """Apply backoff decision to DAG.

        Currently logs the decision; full DAG mutation (reset goals, create
        directives) is delegated to downstream consumers.
        """
        logger.info("Applying backoff decision: %s", decision.reason)

    # ── Background Loops ────────────────────────────────────────────────────────

    async def _verification_loop(self) -> None:
        """Background DAG health verification."""
        interval = getattr(self._config.agent.autopilot, "verify_interval", 30)
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
        interval = getattr(self._config.agent.autopilot, "dreaming_interval", 300)
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

    async def _trigger_dreaming(self) -> None:
        """Trigger dreaming distillation.

        Emits dreaming/awake lifecycle events. Per-mode LLM distillation is
        performed by downstream consumers of the event, not inline here.
        """
        await self._bus.emit_autopilot_dreaming()
        await self._bus.emit_autopilot_awake()
