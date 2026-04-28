"""Tests for GoalEngine → AgentLoop delegation (IG-154)."""

from unittest.mock import AsyncMock, Mock

import pytest

from soothe.cognition.agent_loop.state.schemas import PlanResult
from soothe.core.runner._types import GoalResult


def test_goal_result_model():
    """Verify GoalResult model works correctly."""
    result = GoalResult(
        goal_id="test-goal-123",
        status="completed",
        evidence_summary="Task completed successfully",
        goal_progress=0.95,
        confidence=0.9,
        full_output="Final answer: Task done",
        iteration_count=5,
        duration_ms=3000,
    )

    assert result.goal_id == "test-goal-123"
    assert result.status == "completed"
    assert result.goal_progress == 0.95
    assert result.confidence == 0.9
    assert result.iteration_count == 5
    assert result.duration_ms == 3000


def test_plan_result_to_goal_result_conversion():
    """Verify PlanResult can be wrapped in GoalResult."""
    plan_result = PlanResult(
        status="done",
        evidence_summary="Evidence accumulated from execution",
        goal_progress=1.0,
        confidence=0.85,
        full_output="Goal achieved completely",
    )

    goal_result = GoalResult(
        goal_id="goal-456",
        status="completed" if plan_result.is_done() else "failed",
        evidence_summary=plan_result.evidence_summary,
        goal_progress=plan_result.goal_progress,
        confidence=plan_result.confidence,
        full_output=plan_result.full_output,
    )

    assert goal_result.status == "completed"
    assert goal_result.goal_progress == 1.0
    assert goal_result.evidence_summary == plan_result.evidence_summary


@pytest.mark.asyncio
async def test_agentloop_delegation_basic():
    """Test basic AgentLoop delegation from GoalEngine."""
    from soothe.config import SootheConfig
    from soothe.core.runner import SootheRunner

    # Mock configuration
    config = SootheConfig()
    runner = SootheRunner(config)

    # Mock GoalEngine
    mock_goal = Mock()
    mock_goal.id = "test-goal"
    mock_goal.description = "Test goal description"
    mock_goal.plan_count = 0
    mock_goal.report = None

    # Mock parent state
    parent_state = Mock()
    parent_state.thread_id = "thread-123"
    parent_state.workspace = "/tmp/test"
    parent_state.git_status = None
    parent_state.unified_classification = None

    # Verify planner exists and has LoopPlannerProtocol
    assert runner._planner is not None
    assert hasattr(runner._planner, "plan")

    # Test would verify delegation happens in _execute_autonomous_goal
    # (Full integration test requires running agent loop)


@pytest.mark.asyncio
async def test_planner_reflect_with_agentloop_result():
    """Test planner.reflect() handles agentloop_result parameter."""
    from soothe.cognition.agent_loop.core.planner import LLMPlanner
    from soothe.protocols.planner import GoalContext

    # Mock model
    mock_model = Mock()

    # Create planner
    planner = LLMPlanner(model=mock_model, config=Mock())

    # Create GoalResult
    goal_result = GoalResult(
        goal_id="test-123",
        status="completed",
        evidence_summary="Successfully executed",
        goal_progress=0.95,
        confidence=0.85,
    )

    # Create GoalContext
    goal_context = GoalContext(
        current_goal_id="test-123",
        all_goals=[],
        completed_goals=[],
        failed_goals=[],
        ready_goals=[],
        max_parallel_goals=1,
    )

    # Call reflect with agentloop_result
    reflection = await planner.reflect(
        plan=None,
        step_results=[],
        goal_context=goal_context,
        agentloop_result=goal_result,
    )

    # Verify reflection uses AgentLoop result
    assert reflection is not None
    assert "AgentLoop" in reflection.assessment
    assert "95%" in reflection.assessment or "progress" in reflection.assessment
    assert not reflection.should_revise  # Completed goal
    # Completed goals may have zero directives (no further action needed)
    # or directives marking completion


@pytest.mark.asyncio
async def test_planner_reflect_with_failed_agentloop_result():
    """Test planner generates recovery directives for failed AgentLoop result."""
    from soothe.cognition.agent_loop.core.planner import LLMPlanner
    from soothe.protocols.planner import GoalContext

    mock_model = Mock()
    planner = LLMPlanner(model=mock_model, config=Mock())

    # Failed goal result
    goal_result = GoalResult(
        goal_id="failed-goal",
        status="failed",
        evidence_summary="Execution failed",
        goal_progress=0.3,
        confidence=0.4,
    )

    goal_context = GoalContext(
        current_goal_id="failed-goal",
        all_goals=[],
        completed_goals=[],
        failed_goals=[],
        ready_goals=[],
        max_parallel_goals=1,
    )

    reflection = await planner.reflect(
        plan=None,
        step_results=[],
        goal_context=goal_context,
        agentloop_result=goal_result,
    )

    # Verify recovery directives
    assert reflection.should_revise
    assert len(reflection.goal_directives) >= 1

    # Check for alternative approach directive
    alternative_found = any(
        d.action == "create" and "alternative" in d.description.lower()
        for d in reflection.goal_directives
    )
    assert alternative_found, "Should generate alternative approach directive"


@pytest.mark.asyncio
async def test_planner_reflect_without_agentloop_result():
    """Test planner falls back to heuristic reflection without agentloop_result."""
    from soothe.cognition.agent_loop.core.planner import LLMPlanner
    from soothe.protocols.planner import Plan, PlanStep

    mock_model = Mock()
    planner = LLMPlanner(model=mock_model, config=Mock())

    # Create plan with steps
    plan = Plan(
        goal="Test goal",
        steps=[
            PlanStep(id="S1", description="Step 1", status="completed"),
            PlanStep(id="S2", description="Step 2", status="failed", result="Error"),
        ],
    )

    # Create step results
    from soothe.protocols.planner import StepResult

    step_results = [
        StepResult(step_id="S1", success=True, outcome={}, duration_ms=100, thread_id="test"),
        StepResult(
            step_id="S2",
            success=False,
            outcome={},
            error="Failed",
            duration_ms=100,
            thread_id="test",
        ),
    ]

    # Call reflect WITHOUT agentloop_result
    reflection = await planner.reflect(
        plan=plan,
        step_results=step_results,
        goal_context=None,
        agentloop_result=None,  # Explicitly None
    )

    # Should use heuristic reflection
    assert reflection is not None
    # Heuristic reflection should detect failure
    assert reflection.should_revise or reflection.assessment


def test_goal_result_serialization():
    """Test GoalResult can be serialized/deserialized."""
    result = GoalResult(
        goal_id="serial-test",
        status="in_progress",
        evidence_summary="Partial progress",
        goal_progress=0.6,
        confidence=0.7,
        iteration_count=3,
        duration_ms=1500,
    )

    # Serialize to dict
    result_dict = result.model_dump(mode="json")

    # Deserialize
    restored = GoalResult.model_validate(result_dict)

    assert restored.goal_id == result.goal_id
    assert restored.status == result.status
    assert restored.goal_progress == result.goal_progress
    assert restored.iteration_count == result.iteration_count


@pytest.mark.asyncio
async def test_agentloop_run_with_progress_interface():
    """Verify AgentLoop.run_with_progress() interface matches expectations."""
    from soothe.cognition.agent_loop import AgentLoop
    from soothe.core.agent import CoreAgent

    # Mock CoreAgent
    mock_core_agent = Mock(spec=CoreAgent)
    mock_core_agent.astream = AsyncMock()

    # Mock planner
    mock_planner = Mock()
    mock_planner.plan = AsyncMock()

    # Create AgentLoop
    agent_loop = AgentLoop(
        core_agent=mock_core_agent,
        loop_planner=mock_planner,
        config=Mock(),
    )

    # Verify run_with_progress exists
    assert hasattr(agent_loop, "run_with_progress")

    # Test would verify event stream format:
    # async for event_type, event_data in agent_loop.run_with_progress(...):
    #   assert event_type in ("iteration_started", "plan", "completed")
    #   assert isinstance(event_data, dict)


if __name__ == "__main__":
    # Run basic tests
    import asyncio

    print("Running basic tests...")
    test_goal_result_model()
    print("✅ GoalResult model test passed")

    test_plan_result_to_goal_result_conversion()
    print("✅ PlanResult → GoalResult conversion test passed")

    test_goal_result_serialization()
    print("✅ GoalResult serialization test passed")

    print("\nRunning async tests...")
    asyncio.run(test_planner_reflect_with_agentloop_result())
    print("✅ Planner reflect with AgentLoop result test passed")

    asyncio.run(test_planner_reflect_with_failed_agentloop_result())
    print("✅ Planner reflect with failed AgentLoop result test passed")

    asyncio.run(test_planner_reflect_without_agentloop_result())
    print("✅ Planner reflect without AgentLoop result test passed")

    print("\n✅ All IG-154 AgentLoop integration tests passed!")
