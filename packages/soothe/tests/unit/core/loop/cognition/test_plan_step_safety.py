"""Tests for simple-intake plan step safety guards."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from soothe.foundation.sloop.cognition.plan_step_safety import (
    filter_filler_plan_steps,
    intake_label_from_state,
    max_plan_steps_for_state,
    plan_has_minimum_steps_for_intake,
    simple_intake_should_force_done,
)
from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.state.schemas import (
    FIRST_WAVE_MAX_STEPS,
    LoopState,
    PlanGenerateStep,
    PriorProgressDigest,
    StatusAssessment,
    StepAction,
    StepResult,
    plan_generation_model_for_iteration,
)


def test_intake_label_from_state_reads_intent() -> None:
    state = LoopState(goal="g", thread_id="t1")
    state.intent = SimpleNamespace(intake_label=IntakeLabel.SIMPLE)
    assert intake_label_from_state(state) == IntakeLabel.SIMPLE


def test_plan_has_minimum_steps_missing_decision_behavior() -> None:
    assert plan_has_minimum_steps_for_intake(None, IntakeLabel.COMPLEX, 0) is False
    assert (
        plan_has_minimum_steps_for_intake(
            None,
            IntakeLabel.COMPLEX,
            0,
            treat_missing_as_undersized=False,
        )
        is True
    )


def test_max_plan_steps_caps_simple_intake_on_later_iterations() -> None:
    state = LoopState(goal="g", thread_id="t1", iteration=2)
    state.intent = SimpleNamespace(intake_label=IntakeLabel.SIMPLE)
    assert max_plan_steps_for_state(state) == FIRST_WAVE_MAX_STEPS

    state.intent = SimpleNamespace(intake_label=IntakeLabel.COMPLEX)
    assert max_plan_steps_for_state(state) is None


def test_simple_intake_schema_caps_steps_at_iteration_one() -> None:
    schema = plan_generation_model_for_iteration(1, intake_label=IntakeLabel.SIMPLE)
    steps = [
        PlanGenerateStep(id=f"{i:02d}", description=f"step {i}", expected_output="ok")
        for i in range(3)
    ]
    with pytest.raises(ValidationError):
        schema(type="execute_steps", execution_mode="parallel", steps=steps)


def test_filter_filler_plan_steps_removes_tail_noise() -> None:
    steps = [
        StepAction(id="a", description="Summarize findings"),
        StepAction(id="b", description="The end"),
        StepAction(id="c", description="Stop"),
    ]
    filtered = filter_filler_plan_steps(steps)
    assert [step.description for step in filtered] == ["Summarize findings"]


def test_simple_intake_should_force_done_after_substantial_wave() -> None:
    state = LoopState(goal="world cup", thread_id="t1", iteration=1)
    state.intent = SimpleNamespace(intake_label=IntakeLabel.SIMPLE)
    state.prior_progress = PriorProgressDigest(
        iteration=1,
        derived_progress_hint="high",
        steps_completed=1,
    )
    state.step_results = [
        StepResult(
            step_id="CSF-01",
            success=True,
            duration_ms=1000,
            thread_id="t1",
            subgraph_tool_call_count=2,
        )
    ]
    assessment = StatusAssessment(status="continue", goal_progress="none")

    assert simple_intake_should_force_done(state, assessment) is True


def test_simple_intake_does_not_force_done_without_evidence() -> None:
    state = LoopState(goal="world cup", thread_id="t1", iteration=0)
    state.intent = SimpleNamespace(intake_label=IntakeLabel.SIMPLE)
    assessment = StatusAssessment(status="continue", goal_progress="none")

    assert simple_intake_should_force_done(state, assessment) is False
