"""Tests for synthesizing missing plan-generate ``full_description`` values."""

from __future__ import annotations

from soothe.foundation.sloop.cognition.plan_step_briefs import (
    populate_plan_generate_full_descriptions,
    synthesize_full_description,
)
from soothe.foundation.sloop.state.schemas import PlanGenerateStep, PlanGeneration


def test_synthesize_full_description_includes_goal_and_expected_output() -> None:
    step = PlanGenerateStep(
        id="01",
        description="Discover autopilot RFCs",
        expected_output="List of RFC files and scope areas",
    )
    brief = synthesize_full_description(step, goal="analyze autopilot toward production")
    assert "Discover autopilot RFCs" in brief
    assert "List of RFC files" in brief
    assert "analyze autopilot toward production" in brief


def test_populate_plan_generate_full_descriptions_fills_missing() -> None:
    plan = PlanGeneration(
        type="execute_steps",
        execution_mode="parallel",
        steps=[
            PlanGenerateStep(
                id="01",
                description="Discover autopilot RFCs",
                expected_output="RFC list",
            ),
            PlanGenerateStep(
                id="02",
                description="Analyze implementation",
                full_description=(
                    "Map RFC-204, RFC-222, and RFC-625 requirements to packages/soothe "
                    "autopilot modules; report gaps with file paths and completion status."
                ),
                expected_output="gap analysis",
            ),
        ],
    )
    out = populate_plan_generate_full_descriptions(plan, goal="autopilot production readiness")
    assert out.steps[0].full_description
    assert "RFC list" in (out.steps[0].full_description or "")
    assert out.steps[1].full_description == plan.steps[1].full_description


def test_populate_skips_ask_user_steps() -> None:
    plan = PlanGeneration(
        type="execute_steps",
        execution_mode="parallel",
        steps=[
            PlanGenerateStep(
                id="ASK",
                description="Ask target format",
                kind="ask_user",
                questions=["Which format do you prefer?"],
                expected_output="User answer",
            )
        ],
    )
    out = populate_plan_generate_full_descriptions(plan, goal="refine docs")
    assert out.steps[0].full_description is None
