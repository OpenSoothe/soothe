"""Tests for internal plan action text resolution."""

from __future__ import annotations

from soothe.foundation.sloop.state.schemas import (
    PlanGenerateStep,
    PlanGeneration,
    PlanResult,
)
from soothe.foundation.sloop.utils.plan_action_text import resolve_plan_action_text


def test_resolve_prefers_plan_result_next_action() -> None:
    plan = PlanResult(
        status="done",
        plan_action="keep",
        next_action="I'll grep the adapter logs.",
        plan_reasoning="Let me inspect the adapter first.",
    )
    assert resolve_plan_action_text(plan) == "I'll grep the adapter logs."


def test_resolve_falls_back_to_first_step_description() -> None:
    plan = PlanGeneration(
        type="execute_steps",
        reasoning="Let me inspect the adapter first.",
        steps=[PlanGenerateStep(id="01", description="Read adapter module", expected_output="ok")],
    )
    assert resolve_plan_action_text(plan) == "Read adapter module"


def test_resolve_falls_back_to_reasoning() -> None:
    plan = PlanGeneration(
        type="final",
        reasoning="Let me inspect the adapter first.",
    )
    assert resolve_plan_action_text(plan) == "Let me inspect the adapter first."


def test_resolve_plan_result_uses_plan_reasoning_field() -> None:
    plan = PlanResult(
        status="done",
        plan_action="keep",
        plan_reasoning="Need to verify imports.",
        next_action="",
    )
    assert resolve_plan_action_text(plan) == "Need to verify imports."
