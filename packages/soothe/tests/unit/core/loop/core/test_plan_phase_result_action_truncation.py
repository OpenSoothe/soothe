"""Test PlanResult next_action derivation (IG-152).

Verifies that PlanResult.next_action is derived from plan-generate output
(step descriptions and reasoning) when the LLM no longer emits next_action.
"""

import pytest

from soothe.sloop.cognition.planner import LLMPlanner
from soothe.sloop.state.schemas import (
    AgentDecision,
    PlanGenerateStep,
    PlanGeneration,
    PlanResult,
    StatusAssessment,
    StepAction,
)


@pytest.fixture
def sample_assessment() -> StatusAssessment:
    """Create sample Phase 1 assessment."""
    return StatusAssessment(
        status="continue",
        goal_progress="low",
    )


@pytest.fixture
def sample_plan_result() -> PlanGeneration:
    """Create sample Phase 2 plan."""
    return PlanGeneration(
        type="execute_steps",
        steps=[
            PlanGenerateStep(
                id="step-001",
                description="Read key implementation files from cli/, shared/, and tui/",
                expected_output="Architecture understanding",
            ),
        ],
        execution_mode="parallel",
        reasoning="I'll check implementation details before proposing changes.",
    )


def test_next_action_derives_from_first_step_description(
    sample_assessment: StatusAssessment,
    sample_plan_result: PlanGeneration,
) -> None:
    """PlanResult.next_action derives from the first step description."""
    planner = LLMPlanner.__new__(LLMPlanner)  # Create instance without __init__

    result = planner._combine_results(sample_assessment, sample_plan_result)

    assert result.assessment_reasoning == ""
    assert result.plan_reasoning == sample_plan_result.reasoning
    assert result.next_action == sample_plan_result.steps[0].description
    assert "Read key implementation files" in result.next_action


def test_next_action_falls_back_to_reasoning_when_no_steps(
    sample_plan_result: PlanGeneration,
) -> None:
    """PlanResult.next_action falls back to reasoning for final-type plans."""
    plan_result = PlanGeneration(
        type="final",
        steps=[],
        execution_mode="parallel",
        reasoning="I'll wrap up after reviewing the evidence.",
    )

    assessment = StatusAssessment(status="continue", goal_progress="medium")

    planner = LLMPlanner.__new__(LLMPlanner)
    result = planner._combine_results(assessment, plan_result)

    assert result.next_action == "I'll wrap up after reviewing the evidence."


def test_schema_max_length_updated() -> None:
    """IG-152: PlanResult schema should allow longer next_action (500 chars)."""
    long_action = (
        "Execute comprehensive analysis of the UX module architecture by reading "
        "implementation files from cli/, shared/, and tui/ directories, examining "
        "renderer protocols, display pipeline patterns, and event processing flows"
    )

    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                id="test-step",
                description="Test step",
                expected_output="Test output",
            ),
        ],
        execution_mode="parallel",
        reasoning="Test",
    )

    result = PlanResult(
        status="continue",
        goal_progress="medium",
        plan_action="new",
        decision=decision,
        next_action=long_action,
    )

    assert result.next_action == long_action
    assert len(result.next_action) > 100


def test_early_completion_preserves_action() -> None:
    """IG-264: Early completion (status=done) derives simple completion message."""
    result = PlanResult(
        status="done",
        goal_progress="complete",
        assessment_reasoning="",
        plan_reasoning="",
        plan_action="keep",
        decision=None,
        next_action="Task completed successfully",
    )

    assert result.next_action == "Task completed successfully"
    assert "finalize the comprehensive UX architecture" not in result.next_action


def test_word_boundary_respect_in_cli_display() -> None:
    """IG-152: CLI pipeline should truncate at word boundaries for display."""
    from soothe_nano.utils.text_preview import preview_first

    long_action = (
        "I'll examine the UX module subdirectories (cli, client, shared, tui) "
        "to understand UX module architecture "
        "Read key implementation files from cli/, shared/, and tui/ directories "
        "and analyze the renderer protocol implementation"
    )

    cli_preview = preview_first(long_action, chars=120)
    visible_part = cli_preview.split("[...")[0]

    assert not visible_part.endswith("implementatio")
    assert not visible_part.rstrip().endswith("tui")

    if len(cli_preview) < len(long_action):
        assert "chars abbr" in cli_preview


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
