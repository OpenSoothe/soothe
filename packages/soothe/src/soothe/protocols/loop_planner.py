"""LoopPlannerProtocol -- unified Plan phase for Layer 2 Plan-and-Execute (RFC-0008, IG-153)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from soothe.core.agent_loop.state.schemas import LoopState, PlanResult
from soothe.protocols.planner import PlanContext


@runtime_checkable
class LoopPlannerProtocol(Protocol):
    """Protocol for the AgentLoop Plan step (assessment + optional plan generation).

    Implementations typically perform structured LLM calls (see RFC-604 ``LLMPlanner``:
    ``StatusAssessment`` then, when needed, ``PlanGeneration``) and return a unified
    ``PlanResult``. Naming replaces the older Reason-phase terminology.
    """

    async def plan(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> PlanResult:
        """Assess progress and decide the next executable plan fragment.

        Args:
            goal: Goal description.
            state: Current loop state (iteration, step results, prior plan, current decision).
            context: Capabilities, completed steps summary, workspace, etc.

        Returns:
            PlanResult with status, UX fields, and either ``plan_action='keep'`` or a new
            ``decision`` when ``plan_action='new'``.
        """
        ...
