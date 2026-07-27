"""Terminal 1-step plan builder (RFC-630 §11, IG-599).

Used by:
- ``trivial`` intake branch (``init_or_resume``) — direct execute, no planning
- intake-only wired path (plan bookkeeping only; specialist runs via streamed direct invoke)

Execute (or post-direct-invoke) routes to ``goal_completion`` via
``terminal_after_execute`` / ``wired_route_next`` without a second assess wave.
"""

from __future__ import annotations

from soothe.sloop.cognition.step_deliverable import TRIVIAL_DIRECT_EXPECTED_OUTPUT
from soothe.sloop.state.schemas import (
    AgentDecision,
    PlanResult,
    StepAction,
    resolve_wire_subagent,
)


def build_trivial_plan(
    goal: str,
    *,
    wire_subagent: str | None = None,
    requires_tool_use: bool = False,
) -> PlanResult:
    """Build a minimal 1-step terminal plan.

    Args:
        goal: The user's goal text (verbatim submission).
        wire_subagent: Allowlisted specialist for the wired-subagent route.
        requires_tool_use: Pass 2 signal for the execute deliverable gate.

    Returns:
        A ``PlanResult`` with a single execute step whose action is the goal
        itself and a soft direct-answer ``expected_output`` contract.
    """
    resolved_wire = resolve_wire_subagent(wire_subagent=wire_subagent)
    step = StepAction(
        description=goal,
        expected_output=TRIVIAL_DIRECT_EXPECTED_OUTPUT,
        requires_tool_use=requires_tool_use,
        wire_subagent=resolved_wire,
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
        plan_reasoning="",
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


__all__ = ["build_trivial_plan"]
