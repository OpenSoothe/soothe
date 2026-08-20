"""Single-step plan builder for the wired-subagent delegate path.

Used by the wired-subagent (intake-only specialist) branch for plan
bookkeeping: produces a 1-step ``PlanResult`` carrying the wire-subagent
hint so the direct-invoke specialist can record an execute-step ledger pair
and route to ``goal_completion`` via ``terminal_after_execute`` without a
second assess wave.
"""

from __future__ import annotations

from soothe.sloop.state.schemas import (
    AgentDecision,
    PlanResult,
    StepAction,
    resolve_wire_subagent,
)

# Soft expected-output contract for the wired specialist's direct answer.
_WIRED_SUBAGENT_EXPECTED_OUTPUT = (
    "Direct answer to the user's request. Use tool results when the goal needs "
    "live or external data; otherwise answer from reasoning."
)


def build_wired_subagent_plan(
    goal: str,
    *,
    wire_subagent: str | None = None,
    requires_tool_use: bool = False,
) -> PlanResult:
    """Build a minimal 1-step terminal plan for a wired subagent.

    Args:
        goal: The user's goal text (verbatim submission).
        wire_subagent: Allowlisted specialist for the wired-subagent route.
        requires_tool_use: Execute deliverable-gate signal for the step.

    Returns:
        A ``PlanResult`` with a single execute step whose action is the goal
        itself and a soft direct-answer ``expected_output`` contract.
    """
    resolved_wire = resolve_wire_subagent(wire_subagent=wire_subagent)
    step = StepAction(
        description=goal,
        expected_output=_WIRED_SUBAGENT_EXPECTED_OUTPUT,
        requires_tool_use=requires_tool_use,
        is_dag_root=True,
    )
    if resolved_wire:
        step = step.model_copy(
            update={
                "execution_hint": "subagent",
                "subagent": resolved_wire,
            }
        )

    return PlanResult(
        status="continue",
        goal_progress="none",
        assessment_reasoning="",
        plan_action="new",
        require_goal_completion=False,
        terminal_after_execute=True,
        decision=AgentDecision(
            type="execute_steps",
            execution_mode="parallel",
            reasoning="",
            steps=[step],
        ),
        next_action=goal[:300],
    )


__all__ = ["build_wired_subagent_plan"]
