"""Trivial-branch plan builder (RFC-630 §11).

For the ``trivial`` intake label, ``init_or_resume`` injects a minimal
1-step plan so the loop skips ``plan_assess`` and ``plan_generate``. Execute
runs on a step thread branch; ``terminal_after_execute`` routes to
``goal_completion`` (ledger_direct) without a second assess wave.
"""

from __future__ import annotations

from soothe.foundation.sloop.cognition.simple_bypass import SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT
from soothe.foundation.sloop.state.schemas import AgentDecision, PlanResult, StepAction


def build_trivial_plan(goal: str) -> PlanResult:
    """Build a minimal 1-step plan for the ``trivial`` intake label (RFC-630).

    Args:
        goal: The user's goal (intake LLM's ``goal_description`` or raw goal).

    Returns:
        A ``PlanResult`` with a single execute step whose action is the goal
        itself, no synthetic reasoning prose, and the ``## Result`` evidence
        contract as the step's ``expected_output``.
    """
    return PlanResult(
        status="continue",
        goal_progress="none",
        assessment_reasoning="",
        plan_reasoning="",
        plan_action="new",
        require_goal_completion=False,
        terminal_after_execute=True,
        decision=AgentDecision(
            type="execute_steps",
            execution_mode="parallel",
            reasoning="",
            steps=[
                StepAction(
                    description=goal,
                    expected_output=SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT,
                )
            ],
        ),
        next_action=goal[:300],
    )


__all__ = ["build_trivial_plan"]
