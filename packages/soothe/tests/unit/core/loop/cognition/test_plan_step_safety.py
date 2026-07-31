"""Tests for plan step safety guards (filler filter, max-step cap, simple force-done)."""

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
    simple_intake_should_force_done,
)
from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.state.schemas import (
    DEFAULT_MAX_PLAN_STEPS_PER_WAVE,
    LoopState,
    PriorProgressDigest,
    StatusAssessment,
    StepAction,
    StepExecutionRecord,
)


def test_intake_label_from_state_reads_intent() -> None:
    state = LoopState(goal="g", thread_id="t1")
    state.intent = SimpleNamespace(intake_label=IntakeLabel.SIMPLE)
    assert intake_label_from_state(state) == IntakeLabel.SIMPLE


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
    state._step_results_cache = [
        StepExecutionRecord(
            step_id="CSF-01",
            success=True,
            duration_ms=1000,
            thread_id="t1",
            subgraph_tool_call_count=2,
        )
    ]
    assessment = StatusAssessment(
        status="continue",
        goal_progress="medium",
        require_goal_completion=False,
    )
    assert simple_intake_should_force_done(state, assessment) is True
