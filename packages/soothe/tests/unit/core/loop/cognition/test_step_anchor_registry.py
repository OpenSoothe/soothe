"""Tests for STEP ANCHOR REGISTRY plan-generate grounding."""

from __future__ import annotations

from soothe.context.models import GoalNode, StepExecution, StepNode
from soothe.sloop.cognition.step_anchor_registry import build_step_anchor_registry
from soothe.sloop.state.schemas import LoopState, StepExecutionRecord


def test_registry_empty_without_prior_steps() -> None:
    goal = GoalNode(description="demo")
    state = LoopState(thread_id="t1", goal="demo")
    assert build_step_anchor_registry(goal_node=goal, state=state) == ""


def test_registry_lists_completed_composite_ids() -> None:
    goal = GoalNode(description="demo")
    goal.steps.add_step(
        StepNode(
            id="KFA-01",
            description="Run verify",
            status="completed",
            execution=StepExecution(outcome={"summary": "3 lint errors"}),
        )
    )
    state = LoopState(thread_id="t1", goal="demo")
    state.step_results = [
        StepExecutionRecord(
            step_id="KFA-01",
            success=True,
            outcome={"summary": "3 lint errors"},
            duration_ms=1,
            thread_id="t1",
        )
    ]
    text = build_step_anchor_registry(goal_node=goal, state=state)
    assert "KFA-01 [completed]" in text
    assert "Cross-plan edges" in text
    assert "continues_from" in text


def test_registry_fallback_to_step_results() -> None:
    state = LoopState(thread_id="t1", goal="demo")
    state.step_results = [
        StepExecutionRecord(
            step_id="ABC-02",
            success=True,
            outcome={"type": "text", "summary": "done"},
            duration_ms=1,
            thread_id="t1",
        )
    ]
    text = build_step_anchor_registry(state=state)
    assert "ABC-02 [completed]" in text
