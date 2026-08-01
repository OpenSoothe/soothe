"""Tests for internal plan action text resolution."""

from __future__ import annotations

from soothe.sloop.state.schemas import (
    PlanGenerateStep,
    PlanGeneration,
    PlanResult,
)
from soothe.sloop.utils.plan_action_text import resolve_plan_action_text


def test_resolve_prefers_plan_result_next_action() -> None:
    plan = PlanResult(
        status="done",
        plan_action="keep",
        next_action="I'll grep the adapter logs.",
    )
    assert resolve_plan_action_text(plan) == "I'll grep the adapter logs."


def test_resolve_falls_back_to_first_step_description() -> None:
    plan = PlanGeneration(
        type="execute_steps",
        steps=[PlanGenerateStep(id="01", description="Read adapter module", expected_output="ok")],
    )
    assert resolve_plan_action_text(plan) == "Read adapter module"


def test_resolve_final_without_steps_returns_empty() -> None:
    plan = PlanGeneration(
        type="final",
        steps=[],
    )
    assert resolve_plan_action_text(plan) == ""
