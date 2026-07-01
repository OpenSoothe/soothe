"""Tests for planner ledger projection modes (IG-538)."""

from __future__ import annotations

from soothe.foundation.sloop.prompts.plan_ledger_projection import (
    project_planner_ledger,
    resolve_planner_projection_mode,
)
from soothe.foundation.sloop.state.schemas import LoopState, StepResult
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_resolve_planner_projection_mode_new_goal() -> None:
    state = LoopState(goal="g", thread_id="t", iteration=0)
    assert resolve_planner_projection_mode(state) == "new_goal"


def test_resolve_planner_projection_mode_mid_goal_on_step_results() -> None:
    state = LoopState(goal="g", thread_id="t", iteration=0)
    state.step_results.append(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
    assert resolve_planner_projection_mode(state) == "mid_goal"


def test_project_planner_ledger_mid_goal_includes_execute() -> None:
    state = LoopState(
        goal="g",
        thread_id="t",
        iteration=1,
        loop_messages=[
            LoopHumanMessage(content="exec h", phase="execute_step", thread_id="t"),
            LoopAIMessage(content="exec a", phase="execute_step", thread_id="t"),
        ],
    )
    projected = project_planner_ledger(
        state.loop_messages,
        resolve_planner_projection_mode(state),
        None,
    )
    assert len(projected) == 2
