"""Adaptive plan-generate model selection (IG-671)."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_sdk.intention.models import TaskComplexity

from soothe.sloop.cognition.planner import LLMPlanner
from soothe.sloop.intention.models import IntakeLabel, IntentClassification
from soothe.sloop.state.schemas import (
    GoalComponentStatus,
    LoopState,
    PlanGapAnalysis,
    StepExecutionRecord,
)


def _gap(distance: str) -> PlanGapAnalysis:
    return PlanGapAnalysis(
        components=[
            GoalComponentStatus(
                component="deliverable",
                status="partial",
                evidence="partial",
                gap="remaining",
            )
        ],
        evidence_summary="ok",
        remaining_gaps=["more work"] if distance == "far" else [],
        distance_from_goal=distance,  # type: ignore[arg-type]
        gap_reasoning="gap",
    )


def _planner() -> LLMPlanner:
    think = MagicMock(name="think")
    simple = MagicMock(name="simple")
    near = MagicMock(name="near")
    return LLMPlanner(
        model=think,
        plan_generate_model=think,
        plan_generate_model_simple=simple,
        plan_generate_model_near_gap=near,
    )


def test_select_simple_intake_uses_simple_model() -> None:
    planner = _planner()
    state = LoopState(
        goal="g",
        thread_id="t",
        intent=IntentClassification(
            intake_label=IntakeLabel.SIMPLE,
            task_complexity=TaskComplexity.SIMPLE,
        ),
    )
    assert (
        planner._select_plan_generate_model(state, plan_gap=None, lightweight=False)
        is planner._plan_generate_model_simple
    )


def test_select_lightweight_uses_simple_model() -> None:
    planner = _planner()
    state = LoopState(goal="g", thread_id="t")
    assert (
        planner._select_plan_generate_model(state, plan_gap=None, lightweight=True)
        is planner._plan_generate_model_simple
    )


def test_select_near_gap_uses_near_model() -> None:
    planner = _planner()
    state = LoopState(goal="g", thread_id="t", iteration=1)
    state.add_step_result(
        StepExecutionRecord(step_id="01", success=True, duration_ms=1, thread_id="t")
    )
    assert (
        planner._select_plan_generate_model(state, plan_gap=_gap("near"), lightweight=False)
        is planner._plan_generate_model_near_gap
    )


def test_select_complex_far_uses_think() -> None:
    planner = _planner()
    state = LoopState(
        goal="g",
        thread_id="t",
        intent=IntentClassification(
            intake_label=IntakeLabel.COMPLEX,
            task_complexity=TaskComplexity.COMPLEX,
        ),
    )
    assert (
        planner._select_plan_generate_model(state, plan_gap=_gap("far"), lightweight=False)
        is planner._plan_generate_model
    )
