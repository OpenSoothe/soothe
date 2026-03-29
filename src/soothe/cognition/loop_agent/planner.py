"""PLAN phase logic for Layer 2 agentic loop (RFC-0008)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.cognition.loop_agent.schemas import AgentDecision, LoopState

if TYPE_CHECKING:
    from soothe.protocols.planner import PlanContext, PlannerProtocol

logger = logging.getLogger(__name__)


class PlannerPhase:
    """PLAN phase: Decide what steps to execute.

    This component handles decision creation and reuse logic:
    - Create new AgentDecision when needed (initial or replan)
    - Reuse existing decision when strategy is still valid
    """

    def __init__(self, planner: PlannerProtocol) -> None:
        """Initialize PLAN phase.

        Args:
            planner: Planner protocol implementation
        """
        self.planner = planner

    async def plan(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> AgentDecision:
        """Create or reuse AgentDecision.

        Decision reuse logic:
        - If no existing decision → create new
        - If previous judgment says "replan" → create new
        - If previous judgment says "continue" and has remaining steps → reuse

        Args:
            goal: Goal description
            state: Current loop state
            context: Planning context

        Returns:
            AgentDecision to execute
        """
        # Check if we should reuse existing decision
        if (
            state.current_decision
            and state.has_remaining_steps()
            and state.previous_judgment
            and state.previous_judgment.should_continue()
        ):
            logger.info(
                "Reusing existing AgentDecision (continue strategy) - %d remaining steps",
                len(state.current_decision.get_ready_steps(state.completed_step_ids)),
            )
            return state.current_decision

        # Create new decision
        logger.info(
            "Creating new AgentDecision (iteration %d) - previous judgment: %s",
            state.iteration,
            state.previous_judgment.status if state.previous_judgment else "none",
        )

        decision = await self.planner.decide_steps(
            goal=goal,
            context=context,
            previous_judgment=state.previous_judgment,
        )

        logger.info(
            "Created AgentDecision with %d steps, mode: %s, granularity: %s",
            len(decision.steps),
            decision.execution_mode,
            decision.adaptive_granularity or "unspecified",
        )

        return decision
