"""First-wave plan step cap: schema, truncation, and prompt alignment."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe.foundation.loop.cognition.planner import LLMPlanner
from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
    StepAction,
)
from soothe.protocols.planner import PlanContext


def _step(n: int) -> StepAction:
    return StepAction(
        id=str(n).zfill(2),
        description=f"milestone {n}",
        expected_output="ok",
    )


def test_finalize_truncates_first_wave_to_two_steps() -> None:
    planner = LLMPlanner(MagicMock())
    state = LoopState(goal="test", thread_id="t1", iteration=0, max_iterations=8)
    decision = AgentDecision(
        type="execute_steps",
        steps=[_step(i) for i in range(1, 6)],
        execution_mode="parallel",
        reasoning="over-planned",
    )
    result = PlanResult(
        status="continue",
        goal_progress="none",
        plan_action="new",
        decision=decision,
        next_action="Start.",
    )

    finalized = planner._finalize_generated_plan_result(
        result=result,
        state=state,
        context=PlanContext(workspace="/tmp"),
        goal="test",
    )

    assert finalized.decision is not None
    assert len(finalized.decision.steps) == 2
    assert finalized.decision.steps[0].description == "milestone 1"
    assert finalized.decision.steps[1].description == "milestone 2"


def test_finalize_keeps_three_steps_on_later_iteration() -> None:
    planner = LLMPlanner(MagicMock())
    state = LoopState(goal="test", thread_id="t1", iteration=1, max_iterations=8)
    decision = AgentDecision(
        type="execute_steps",
        steps=[_step(i) for i in range(1, 4)],
        execution_mode="parallel",
        reasoning="replan",
    )
    result = PlanResult(
        status="continue",
        goal_progress="low",
        plan_action="new",
        decision=decision,
        next_action="Continue.",
    )

    finalized = planner._finalize_generated_plan_result(
        result=result,
        state=state,
        context=PlanContext(workspace="/tmp"),
        goal="test",
    )

    assert finalized.decision is not None
    assert len(finalized.decision.steps) == 3
