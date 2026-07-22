"""Tests for the step deliverable gate (IG-569)."""

from __future__ import annotations

from soothe.sloop.cognition.step_deliverable import (
    TRIVIAL_DIRECT_EXPECTED_OUTPUT,
    StepDeliverableSpec,
    evaluate_step_deliverable_structural,
    resolve_step_deliverable_spec,
    step_has_deliverable_gate,
)
from soothe.sloop.state.schemas import StepAction


def test_trivial_expected_output_is_soft_direct_answer() -> None:
    assert "Direct answer" in TRIVIAL_DIRECT_EXPECTED_OUTPUT
    assert "## Result" not in TRIVIAL_DIRECT_EXPECTED_OUTPUT


def test_structural_incomplete_when_tools_required_but_missing() -> None:
    verdict = evaluate_step_deliverable_structural(
        spec=StepDeliverableSpec(requires_tool_use=True),
        final_ai_text="I'll look that up.",
        main_tool_call_count=0,
        stream_outcomes=[],
        all_tools_failed=False,
        hit_tool_budget=False,
        min_answer_chars=20,
    )
    assert not verdict.complete
    assert verdict.failure_mode.value == "no_tools_when_needed"


def test_structural_complete_when_tools_ran_and_answer_present() -> None:
    verdict = evaluate_step_deliverable_structural(
        spec=StepDeliverableSpec(requires_tool_use=True),
        final_ai_text="The current weather in Shanghai is sunny, 22°C.",
        main_tool_call_count=1,
        stream_outcomes=[{"type": "code_exec", "tool_name": "run_command", "has_error": False}],
        all_tools_failed=False,
        hit_tool_budget=False,
        min_answer_chars=20,
    )
    assert verdict.complete


def test_structural_complete_for_reasoning_without_tools() -> None:
    verdict = evaluate_step_deliverable_structural(
        spec=StepDeliverableSpec(requires_tool_use=False),
        final_ai_text="## Result\n\nAnswer: 4",
        main_tool_call_count=0,
        stream_outcomes=[],
        all_tools_failed=False,
        hit_tool_budget=False,
        min_answer_chars=20,
    )
    assert verdict.complete


def test_resolve_spec_none_when_gate_disabled() -> None:
    step = StepAction(description="explore repo")
    assert resolve_step_deliverable_spec(step) is None
    assert step_has_deliverable_gate(step) is False


def test_resolve_spec_from_step_metadata() -> None:
    step = StepAction(description="weather", requires_tool_use=True)
    spec = resolve_step_deliverable_spec(step)
    assert spec is not None
    assert spec.requires_tool_use is True
    assert step_has_deliverable_gate(step) is True
