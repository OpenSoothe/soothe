"""Tests for synthesizing missing plan-generate ``full_description`` values."""

from __future__ import annotations

from soothe.sloop.cognition.plan_step_briefs import (
    populate_plan_generate_full_descriptions,
    synthesize_full_description,
)
from soothe.sloop.state.schemas import PlanGenerateStep, PlanGeneration


def test_synthesize_full_description_is_step_local_without_goal() -> None:
    step = PlanGenerateStep(
        id="01",
        description="Discover autopilot RFCs",
        expected_output="List of RFC files and scope areas",
    )
    brief = synthesize_full_description(step)
    assert "Discover autopilot RFCs" in brief
    assert "List of RFC files" in brief
    assert "Context: this step advances the goal" not in brief


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
    out = populate_plan_generate_full_descriptions(plan)
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
    out = populate_plan_generate_full_descriptions(plan)
    assert out.steps[0].full_description is None


def test_synthesize_includes_image_facts_when_vision_present() -> None:
    step = PlanGenerateStep(
        id="01",
        description="Extract UI labels from screenshot",
        expected_output="Label list",
    )
    brief = synthesize_full_description(
        step,
        vision_summary="Login form with email field and blue Submit button.",
    )
    assert "Image facts:" in brief
    assert "Submit button" in brief
    assert "Context: this step advances the goal" not in brief


def test_populate_with_goal_vision_block_adds_image_facts() -> None:
    goal = (
        "What does this screen show?\n\n"
        "--- Vision summary ---\n"
        "Settings page with Dark Mode toggle enabled.\n"
        "---\n"
    )
    plan = PlanGeneration(
        type="execute_steps",
        execution_mode="parallel",
        steps=[
            PlanGenerateStep(
                id="01",
                description="Describe the screenshot",
                expected_output="Short description",
            ),
        ],
    )
    out = populate_plan_generate_full_descriptions(plan, goal=goal)
    assert "Image facts:" in (out.steps[0].full_description or "")
    assert "Dark Mode" in (out.steps[0].full_description or "")
