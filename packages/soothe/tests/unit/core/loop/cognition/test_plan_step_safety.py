"""Tests for simple-intake plan step safety guards."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from soothe.sloop.cognition.plan_generation_wire import (
    capped_plan_generation_wire_model,
)
from soothe.sloop.cognition.plan_step_safety import (
    filter_filler_plan_steps,
    intake_label_from_state,
    plan_has_minimum_steps_for_intake,
    simple_intake_should_force_done,
)
from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.state.schemas import (
    DEFAULT_MAX_PLAN_STEPS_PER_WAVE,
    LoopState,
    PriorProgressDigest,
    StatusAssessment,
    StepAction,
    StepResult,
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


def test_capped_wire_schema_rejects_over_max_steps() -> None:
    schema = capped_plan_generation_wire_model()
    steps = [
        {
            "description": f"step {i}",
            "expected_output": "ok",
            "dependencies": [],
        }
        for i in range(DEFAULT_MAX_PLAN_STEPS_PER_WAVE + 1)
    ]
    with pytest.raises(ValidationError):
        schema(reasoning="Plan wave.", steps=steps)


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
