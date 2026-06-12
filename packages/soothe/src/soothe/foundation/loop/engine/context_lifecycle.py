"""ContextEngine lifecycle manager for one AgentLoop goal run (RFC-624 Phase 3d).

Encapsulates all ContextEngine interactions so that graph nodes never call CE
methods directly. When CE is disabled, all methods are no-ops. When enabled,
each method handles goal lifecycle, step feedback, projection, and persistence
atomically with error isolation — CE failures never propagate to graph nodes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from soothe.context.engine import ContextEngine
    from soothe.context.projection import ContextBundle
    from soothe.foundation.loop.state.schemas import PlanResult, StepResult

logger = logging.getLogger(__name__)


class ContextEngineLifecycle:
    """All ContextEngine interactions for one AgentLoop goal run.

    CE disabled → all methods are no-ops.
    CE enabled → each method handles goal lifecycle, step feedback,
    projection, persistence atomically.
    """

    def __init__(
        self,
        context_engine: ContextEngine | None,
        goal_id: str | None,
    ) -> None:
        self._ce = context_engine
        self._goal_id = goal_id

    @property
    def enabled(self) -> bool:
        return self._ce is not None and self._goal_id is not None

    # ── Lifecycle hooks ─────────────────────────────────────────────

    async def on_goal_start(self, workspace: Path | None = None) -> None:
        """Called at agent_loop startup after goal creation.

        Loads semantic context (CLAUDE.md, AGENTS.md, MEMORY.md).
        """
        if not self.enabled:
            return
        try:
            if workspace is not None:
                self._ce._semantic.workspace = workspace
                self._ce._semantic.load_project_instructions()
                self._ce._semantic.load_agent_instructions()
                self._ce._semantic.load_memory()
        except Exception:
            logger.warning("[CE-Lifecycle] on_goal_start failed", exc_info=True)

    async def on_plan_ingested(
        self,
        plan_result: PlanResult,
        plan_id: str | None,
        iteration: int,
    ) -> None:
        """Called after plan_manager.ingest_plan() in plan_assess/resolve_decision.

        Persists CE state to capture new step nodes.
        """
        if not self.enabled:
            return
        try:
            await self._ce.save()
        except Exception:
            logger.warning("[CE-Lifecycle] on_plan_ingested save failed", exc_info=True)

    async def on_steps_executed(self, step_results: list[StepResult]) -> None:
        """Called after plan_manager.record_step_outcomes() in record_iteration.

        Dual-path: sync mutations already ran via StepPlanningSubengine.
        This fires async CE APIs (complete_step/fail_step) for callbacks
        and events, then persists CE state.
        """
        if not self.enabled:
            return
        try:
            from soothe.context.models import StepExecution

            for r in step_results:
                execution = StepExecution(
                    duration_ms=r.duration_ms,
                    thread_id=r.thread_id,
                    error=r.error,
                )
                if r.success:
                    asyncio.create_task(self._ce.complete_step(self._goal_id, r.step_id, execution))
                else:
                    asyncio.create_task(self._ce.fail_step(self._goal_id, r.step_id, execution))

            await self._ce.save()
        except Exception:
            logger.warning("[CE-Lifecycle] on_steps_executed failed", exc_info=True)

    async def on_goal_complete(
        self,
        status: str,
        plan_result: PlanResult | None = None,
    ) -> None:
        """Called in goal_completion to close the goal lifecycle.

        Completes or fails the goal, then persists final CE state.
        """
        if not self.enabled:
            return
        try:
            if status == "done":
                await self._ce.complete_goal(self._goal_id)
            else:
                error_msg = ""
                if plan_result is not None:
                    error_msg = plan_result.assessment_reasoning or "goal failed"
                await self._ce.fail_goal(self._goal_id, error_msg)
            await self._ce.save()
        except Exception:
            logger.warning("[CE-Lifecycle] on_goal_complete failed", exc_info=True)

    # ── Projection ──────────────────────────────────────────────────

    async def get_context_bundle(self) -> ContextBundle | None:
        """Build ContextBundle via CE projection for plan_generate.

        Returns None when CE is disabled or projection fails.
        """
        if not self.enabled:
            return None
        try:
            return await self._ce.project(goal_id=self._goal_id)
        except Exception:
            logger.debug("[CE-Lifecycle] get_context_bundle failed", exc_info=True)
            return None
