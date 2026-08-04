"""Tests for interrupt-resume CE goal reuse helpers (IG-684)."""

from __future__ import annotations

from types import SimpleNamespace

from soothe.sloop.engine.strange_loop import _hydrate_previous_plan_from_ce
from soothe.sloop.state.schemas import LoopState, PlanResult


def test_hydrate_previous_plan_from_ce_dict() -> None:
    state = LoopState(goal="retry", thread_id="t")
    ce_goal = SimpleNamespace(
        id="g1",
        previous_plan={
            "status": "continue",
            "goal_progress": "medium",
            "plan_action": "keep",
            "next_action": "retry failed step",
        },
    )
    _hydrate_previous_plan_from_ce(state, ce_goal)
    assert state.previous_plan is not None
    assert state.previous_plan.plan_action == "keep"
    assert state.previous_plan.goal_progress == "medium"


def test_hydrate_previous_plan_skips_when_already_set() -> None:
    existing = PlanResult(status="continue", goal_progress="low", plan_action="keep")
    state = LoopState(goal="retry", thread_id="t", previous_plan=existing)
    ce_goal = SimpleNamespace(
        id="g1",
        previous_plan={"status": "continue", "goal_progress": "high", "plan_action": "keep"},
    )
    _hydrate_previous_plan_from_ce(state, ce_goal)
    assert state.previous_plan is existing
