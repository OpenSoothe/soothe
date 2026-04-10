"""Tests for wave metrics aggregation in Executor (IG-132)."""

import pytest

from soothe.cognition.agent_loop.executor import Executor
from soothe.cognition.agent_loop.schemas import LoopState, StepResult
from soothe.config import SootheConfig


@pytest.fixture
def mock_core_agent():
    """Mock CoreAgent for testing."""

    class MockCoreAgent:
        pass

    return MockCoreAgent()


@pytest.fixture
def config():
    """Standard config for testing."""
    return SootheConfig()


@pytest.fixture
def state():
    """Fresh LoopState for testing."""
    return LoopState(
        goal="Test goal",
        thread_id="test-thread",
    )


def test_aggregate_metrics_basic(mock_core_agent, config, state):
    """Basic metrics aggregation from step results."""
    executor = Executor(mock_core_agent, config=config)

    step_results = [
        StepResult(
            step_id="step1",
            success=True,
            output="Output 1",
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=2,
            subagent_task_completions=1,
            hit_subagent_cap=False,
        ),
        StepResult(
            step_id="step2",
            success=True,
            output="Output 2",
            duration_ms=150,
            thread_id="test-thread",
            tool_call_count=3,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
    ]

    output = "Combined output text"
    executor._aggregate_wave_metrics(step_results, output, state)

    assert state.last_wave_tool_call_count == 5  # 2 + 3
    assert state.last_wave_subagent_task_count == 1  # 1 + 0
    assert state.last_wave_hit_subagent_cap is False
    assert state.last_wave_output_length == len(output)
    assert state.last_wave_error_count == 0


def test_aggregate_metrics_with_errors(mock_core_agent, config, state):
    """Metrics aggregation counts failed steps."""
    executor = Executor(mock_core_agent, config=config)

    step_results = [
        StepResult(
            step_id="step1",
            success=True,
            output="Success",
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=2,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
        StepResult(
            step_id="step2",
            success=False,
            error="Failed",
            error_type="execution",
            duration_ms=50,
            thread_id="test-thread",
            tool_call_count=0,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
    ]

    executor._aggregate_wave_metrics(step_results, "Output", state)

    assert state.last_wave_error_count == 1


def test_aggregate_metrics_cap_hit(mock_core_agent, config, state):
    """Metrics aggregation detects cap hit."""
    executor = Executor(mock_core_agent, config=config)

    step_results = [
        StepResult(
            step_id="step1",
            success=True,
            output="Output",
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=2,
            subagent_task_completions=2,
            hit_subagent_cap=True,
        ),
    ]

    executor._aggregate_wave_metrics(step_results, "Output", state)

    assert state.last_wave_hit_subagent_cap is True


def test_aggregate_metrics_empty_results(mock_core_agent, config, state):
    """Metrics aggregation handles empty results."""
    executor = Executor(mock_core_agent, config=config)

    executor._aggregate_wave_metrics([], "", state)

    assert state.last_wave_tool_call_count == 0
    assert state.last_wave_subagent_task_count == 0
    assert state.last_wave_hit_subagent_cap is False
    assert state.last_wave_output_length == 0
    assert state.last_wave_error_count == 0


def test_aggregate_metrics_context_window_estimation(mock_core_agent, config, state):
    """Metrics aggregation estimates context window usage."""
    executor = Executor(mock_core_agent, config=config)

    # Create output of known length
    output = "x" * 4000  # 4000 chars ≈ 1000 tokens

    step_results = [
        StepResult(
            step_id="step1",
            success=True,
            output=output,
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=1,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
    ]

    executor._aggregate_wave_metrics(step_results, output, state)

    # Should estimate ~1000 tokens (4000 chars / 4)
    assert state.total_tokens_used == 1000
    # Should be ~0.5% of 200k context limit
    assert 0.004 <= state.context_percentage_consumed <= 0.006


def test_aggregate_metrics_cumulative_tokens(mock_core_agent, config, state):
    """Context window metrics accumulate across waves."""
    executor = Executor(mock_core_agent, config=config)

    # First wave
    output1 = "x" * 4000
    step_results1 = [
        StepResult(
            step_id="step1",
            success=True,
            output=output1,
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=1,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
    ]
    executor._aggregate_wave_metrics(step_results1, output1, state)
    first_total = state.total_tokens_used

    # Second wave
    output2 = "y" * 8000
    step_results2 = [
        StepResult(
            step_id="step2",
            success=True,
            output=output2,
            duration_ms=150,
            thread_id="test-thread",
            tool_call_count=2,
            subagent_task_completions=1,
            hit_subagent_cap=False,
        ),
    ]
    executor._aggregate_wave_metrics(step_results2, output2, state)

    # Should accumulate: 1000 + 2000 = 3000
    assert state.total_tokens_used == first_total + 2000
    # Should be ~1.5% of 200k context limit
    assert 0.014 <= state.context_percentage_consumed <= 0.016


def test_aggregate_metrics_multiple_cap_hits(mock_core_agent, config, state):
    """OR logic for cap hit across multiple steps."""
    executor = Executor(mock_core_agent, config=config)

    step_results = [
        StepResult(
            step_id="step1",
            success=True,
            output="Output 1",
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=1,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
        StepResult(
            step_id="step2",
            success=True,
            output="Output 2",
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=1,
            subagent_task_completions=1,
            hit_subagent_cap=True,
        ),
    ]

    executor._aggregate_wave_metrics(step_results, "Output", state)

    # Any cap hit = True
    assert state.last_wave_hit_subagent_cap is True
