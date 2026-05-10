"""Tests for wave metrics aggregation in Executor (IG-132)."""

import pytest

from soothe.config import SootheConfig
from soothe.core.agent_loop.engine.executor import Executor
from soothe.core.agent_loop.state.schemas import LoopState, StepAction, StepResult
from soothe.core.agent_loop.utils.messages import LoopAIMessage, LoopHumanMessage


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
    messages = []  # Empty messages for test
    executor._aggregate_wave_metrics(step_results, output, messages, state)

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

    executor._aggregate_wave_metrics(step_results, "Output", [], state)

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

    executor._aggregate_wave_metrics(step_results, "Output", [], state)

    assert state.last_wave_hit_subagent_cap is True


def test_aggregate_metrics_empty_results(mock_core_agent, config, state):
    """Metrics aggregation handles empty results."""
    executor = Executor(mock_core_agent, config=config)

    executor._aggregate_wave_metrics([], "", [], state)

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

    executor._aggregate_wave_metrics(step_results, output, [], state)

    # Tiktoken estimates 500 tokens for 4000 'x' chars (IG-151)
    assert state.total_tokens_used == 500
    # Should be ~0.25% of 200k context limit
    assert 0.002 <= state.context_percentage_consumed <= 0.003


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
    executor._aggregate_wave_metrics(step_results1, output1, [], state)
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
    executor._aggregate_wave_metrics(step_results2, output2, [], state)

    # Tiktoken estimates: 500 (first) + 2000 (second) = 2500 total
    # First: 4000 'x' chars = 500 tokens
    # Second: 8000 'y' chars = 2000 tokens
    assert state.total_tokens_used == first_total + 2000
    # Should be ~1.25% of 200k context limit
    assert 0.012 <= state.context_percentage_consumed <= 0.013


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

    executor._aggregate_wave_metrics(step_results, "Output", [], state)

    # Any cap hit = True
    assert state.last_wave_hit_subagent_cap is True


def test_record_batch_ledger_pairs_splits_wave_duration(mock_core_agent, config, state):
    """RFC-214 batch: wave wall time is split across StepResults (sums to wave duration)."""
    executor = Executor(mock_core_agent, config=config)
    steps = [
        StepAction(id="a", description="one", dependencies=[]),
        StepAction(id="b", description="two", dependencies=[]),
        StepAction(id="c", description="three", dependencies=[]),
    ]
    step_messages = [
        LoopHumanMessage(
            content="h1", thread_id=state.thread_id, iteration=1, phase="execute_step"
        ),
        LoopHumanMessage(
            content="h2", thread_id=state.thread_id, iteration=1, phase="execute_step"
        ),
        LoopHumanMessage(
            content="h3", thread_id=state.thread_id, iteration=1, phase="execute_step"
        ),
    ]
    step_outcomes = {
        "a": LoopAIMessage(content="o1", thread_id=state.thread_id, iteration=1),
        "b": LoopAIMessage(content="o2", thread_id=state.thread_id, iteration=1),
        "c": LoopAIMessage(content="o3", thread_id=state.thread_id, iteration=1),
    }
    wave_ms = 100
    results = executor._record_batch_ledger_pairs(
        state,
        step_messages,
        step_outcomes,
        steps,
        duration_ms=wave_ms,
        subagent_task_completions=0,
        hit_subagent_cap=False,
        tool_call_count=5,
    )
    assert [r.duration_ms for r in results] == [34, 33, 33]
    assert sum(r.duration_ms for r in results) == wave_ms
    assert results[0].tool_call_count == 5
    assert results[1].tool_call_count == 0
