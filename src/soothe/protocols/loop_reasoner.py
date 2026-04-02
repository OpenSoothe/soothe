"""LoopReasonerProtocol -- unified Reason phase for Layer 2 ReAct (RFC-0008)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from soothe.cognition.loop_agent.schemas import LoopState, ReasonResult
from soothe.protocols.planner import PlanContext


@runtime_checkable
class LoopReasonerProtocol(Protocol):
    """Protocol for the Layer 2 Reason step (planning + progress in one LLM call)."""

    async def reason(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> ReasonResult:
        """Assess progress and decide the next executable plan fragment.

        Args:
            goal: Goal description.
            state: Current loop state (iteration, step results, prior reason, current decision).
            context: Capabilities, completed steps summary, workspace, etc.

        Returns:
            ReasonResult with status, UX fields, and either ``plan_action='keep'`` or a new
            ``decision`` when ``plan_action='new'``.
        """
        ...
