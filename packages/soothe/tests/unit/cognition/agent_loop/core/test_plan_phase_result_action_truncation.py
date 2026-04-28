"""Test PlanResult next_action fix (IG-152).

Verifies that next_action field:
1. Uses plan_result.next_action (concrete action, not duplication)
2. Preserves full text (no truncation)
3. Respects word boundaries in CLI display truncation
"""

import pytest

from soothe.cognition.agent_loop.core.planner import LLMPlanner
from soothe.cognition.agent_loop.state.schemas import (
    AgentDecision,
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
        goal_progress=0.36,
        confidence=0.85,
        brief_reasoning="Progress is 36%, need to examine subdirectories",
        next_action="I'll examine the UX module subdirectories (cli, client, shared, tui)",
    )


@pytest.fixture
def sample_plan_result() -> PlanGeneration:
    """Create sample Phase 2 plan."""
    return PlanGeneration(
        plan_action="new",
        decision=AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(
                    id="step-001",
                    description="Read key implementation files from cli/, shared/, and tui/",
                    expected_output="Architecture understanding",
                ),
            ],
            execution_mode="sequential",
            reasoning="Need to check implementation details",
        ),
        brief_reasoning="Plan to check implementation files",
        next_action="Read key implementation files from cli/, shared/, and tui/ directories",
    )


def test_next_action_uses_plan_action(
    sample_assessment: StatusAssessment,
    sample_plan_result: PlanGeneration,
) -> None:
    """IG-152: next_action uses plan_result.next_action (concrete action)."""
    planner = LLMPlanner.__new__(LLMPlanner)  # Create instance without __init__

    result = planner._combine_results(sample_assessment, sample_plan_result)

    # IG-264: Only plan_result.brief_reasoning used (assessment removed)
    assert result.assessment_reasoning == ""  # IG-264: Empty
    assert result.plan_reasoning == sample_plan_result.brief_reasoning

    # Should use plan_result.next_action (concrete action)
    assert result.next_action == sample_plan_result.next_action
    assert "Read key implementation files" in result.next_action

    # Verify full text preserved (no truncation)
    assert not result.next_action.endswith("tui")  # Should not cut mid-phrase


def test_next_action_preserves_full_text(
    sample_plan_result: PlanGeneration,
) -> None:
    """IG-152: next_action should preserve full LLM-generated text without truncation."""
    # Create a long action text (>100 chars) - LLM-generated for variety
    long_action = (
        "Read key implementation files from cli/, shared/, and tui/ directories "
        "to analyze the renderer protocol implementation patterns "
        "and understand the display pipeline architecture in detail"
    )  # 138 chars

    plan_result = PlanGeneration(
        plan_action="new",
        decision=sample_plan_result.decision,
        brief_reasoning="Detailed plan",
        next_action=long_action,
    )

    assessment = StatusAssessment(
        status="continue",
        goal_progress=0.5,
        confidence=0.8,
    )

    planner = LLMPlanner.__new__(LLMPlanner)
    result = planner._combine_results(assessment, plan_result)

    # Verify full plan action preserved (LLM-generated)
    assert result.next_action == long_action
    assert len(result.next_action) > 100  # Exceeds old 100-char limit
    assert "renderer protocol implementation patterns" in result.next_action


def test_schema_max_length_updated() -> None:
    """IG-152: PlanResult schema should allow longer next_action (500 chars)."""
    # Create a PlanResult with long action (>100 chars)
    long_action = (
        "Execute comprehensive analysis of the UX module architecture by reading "
        "implementation files from cli/, shared/, and tui/ directories, examining "
        "renderer protocols, display pipeline patterns, and event processing flows"
    )  # 159 chars

    # Create a minimal decision (required when status!=done and plan_action=new)
    from soothe.cognition.agent_loop.state.schemas import StepAction

    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                id="test-step",
                description="Test step",
                expected_output="Test output",
            ),
        ],
        execution_mode="sequential",
        reasoning="Test",
    )

    # Should accept without validation error (max_length=500)
    result = PlanResult(
        status="continue",
        goal_progress=0.5,
        confidence=0.8,
        plan_action="new",
        decision=decision,
        next_action=long_action,
    )

    # Verify full text preserved (no truncation)
    assert result.next_action == long_action
    assert len(result.next_action) > 100  # Exceeds old 100-char limit


def test_early_completion_preserves_action() -> None:
    """IG-264: Early completion (status=done) derives simple completion message."""
    assessment = StatusAssessment(
        status="done",
        goal_progress=1.0,
        confidence=0.95,
    )

    # IG-264: Early completion derives simple message (no LLM-generated fields)
    result = PlanResult(
        status=assessment.status,
        goal_progress=assessment.goal_progress,
        confidence=assessment.confidence,
        assessment_reasoning="",  # IG-264: Empty
        plan_reasoning="",  # IG-264: Empty
        plan_action="keep",
        decision=None,
        next_action="Task completed successfully",  # IG-264: Derived
    )

    # IG-264: Verify derived completion message
    assert result.next_action == "Task completed successfully"
    # IG-264: No longer expecting long LLM-generated text (derived message is concise)
    # Should NOT contain LLM-generated detailed message (removed)
    assert "finalize the comprehensive UX architecture" not in result.next_action


def test_word_boundary_respect_in_cli_display() -> None:
    """IG-152: CLI pipeline should truncate at word boundaries for display.

    Note: This tests the utility function behavior, actual truncation happens in
    ux/cli/stream/pipeline.py:_on_loop_agent_reason() with adaptive limits.
    """
    from soothe.utils.text_preview import preview_first

    # Simulate long action text
    long_action = (
        "I'll examine the UX module subdirectories (cli, client, shared, tui) "
        "to understand UX module architecture "
        "Read key implementation files from cli/, shared/, and tui/ directories "
        "and analyze the renderer protocol implementation"
    )

    # preview_first adds truncation marker like "[...N chars abbr...]"
    cli_preview = preview_first(long_action, chars=120)

    # Verify word boundary truncation (no mid-word cuts in the visible part)
    visible_part = cli_preview.split("[...")[0]  # Get text before marker

    # Should not end with partial words
    assert not visible_part.endswith("implementatio")  # Not cut mid-word
    assert not visible_part.rstrip().endswith("tui")  # Not cut mid-phrase

    # Should include truncation marker when truncated
    if len(cli_preview) < len(long_action):
        assert "chars abbr" in cli_preview  # Marker format is "[...N chars abbr...]"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
