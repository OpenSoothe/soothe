"""LoopPlannerProtocol -- unified Plan phase for Layer 2 Plan-and-Execute (RFC-0008, IG-153)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from soothe.foundation.loop.state.schemas import (
    ContinuationAssessment,
    LoopState,
    PlanResult,
    StatusAssessment,
)
from soothe.protocols.planner import PlanContext


@runtime_checkable
class LoopPlannerProtocol(Protocol):
    """Protocol for the StrangeLoop Plan step (assessment + optional plan generation).

    Implementations typically perform structured LLM calls (see RFC-604 ``LLMPlanner``:
    ``StatusAssessment`` then, when needed, ``PlanGeneration``) and return a unified
    ``PlanResult``. Naming replaces the older Reason-phase terminology.
    """

    async def plan(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        plan_manager: Any = None,
    ) -> PlanResult:
        """Assess progress and decide the next executable plan fragment.

        Args:
            goal: Goal description.
            state: Current loop state (iteration, step results, prior plan, current decision).
            context: Capabilities, completed steps summary, workspace, etc.
            plan_manager: Optional PlanManager for DAG-aware progressive planning.

        Returns:
            PlanResult with status, UX fields, and either ``plan_action='keep'`` or a new
            ``decision`` when ``plan_action='new'``.
        """
        ...

    async def assess_status(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> StatusAssessment:
        """Run assess-only status evaluation for the current iteration."""
        ...

    async def generate_from_assessment(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        assessment: StatusAssessment,
        *,
        plan_manager: Any = None,
    ) -> PlanResult:
        """Generate or keep an execution plan after assess determines work remains."""
        ...

    async def assess_continuation(
        self,
        *,
        current_goal: str,
        prior_goals: list[dict],
        capabilities: list[str],
        thread_id: str | None = None,
    ) -> ContinuationAssessment:
        """RFC-226: iter=0 discriminator for continuation queries.

        Routes a follow-up agentic query in an existing loop to either a
        terminal bootstrap (single execute step using prior context) or the
        full ``plan_generate`` flow. Called from ``plan_assess`` when
        ``continue_loop_mode`` is True and the loop has prior completed goals.
        """
        ...
