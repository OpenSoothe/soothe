"""LoopPlannerProtocol -- unified Plan phase for Layer 2 Plan-and-Execute (RFC-0008, IG-153)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from soothe.cognition.agent_loop.schemas import LoopState, PlanResult
from soothe.protocols.planner import PlanContext


@runtime_checkable
class LoopPlannerProtocol(Protocol):
    """Protocol for the Layer 2 Plan step (planning + progress in one LLM call).

    The Plan phase combines planning, progress assessment, and goal-distance estimation
    in a single structured response (PlanResult). This replaces the old Reason phase
    terminology to better reflect the two-phase Plan-and-Execute architecture.
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
