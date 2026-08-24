"""Tests for wave metrics aggregation in Executor."""

import pytest

from soothe.config import SootheConfig
from soothe.sloop.engine.execute.executor import Executor
from soothe.sloop.state.schemas import LoopState, StepExecutionRecord


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
        StepExecutionRecord(
            step_id="step1",
            success=True,
            output="Output 1",
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=2,
            subagent_task_completions=1,
            hit_subagent_cap=False,
        ),
        StepExecutionRecord(
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
        StepExecutionRecord(
            step_id="step1",
            success=True,
            output="Success",
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=2,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
        StepExecutionRecord(
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
        StepExecutionRecord(
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
    """Metrics aggregation estimates context window usage (input + output).

    IG-761: the fallback path estimates BOTH input and output tokens via the
    unified ``estimate_token_usage`` API, never output alone. With no
    ``usage_metadata`` present, the estimate covers prompt + response.
    """
    from langchain_core.messages import AIMessage, HumanMessage

    executor = Executor(mock_core_agent, config=config)

    # Realistic wave: a human prompt + an AI response (no usage_metadata →
    # estimation path). Previously the fallback counted output only.
    messages = [
        HumanMessage(content="x" * 4000),
        AIMessage(content="y" * 4000),
    ]

    step_results = [
        StepExecutionRecord(
            step_id="step1",
            success=True,
            output="y" * 4000,
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=1,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
    ]

    executor._aggregate_wave_metrics(step_results, "y" * 4000, messages, state)

    # Input + output both estimated (each ~500 tokens) plus structural
    # overhead. Total must exceed the output-only count (500) of the old
    # behavior, proving input tokens are now counted.
    assert state.total_tokens_used > 500
    assert state.context_percentage_consumed > 0


def test_aggregate_metrics_cumulative_tokens(mock_core_agent, config, state):
    """Context window metrics accumulate across waves (input + output)."""
    from langchain_core.messages import AIMessage, HumanMessage

    executor = Executor(mock_core_agent, config=config)

    # First wave
    messages1 = [
        HumanMessage(content="x" * 4000),
        AIMessage(content="a" * 4000),
    ]
    step_results1 = [
        StepExecutionRecord(
            step_id="step1",
            success=True,
            output="a" * 4000,
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=1,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
    ]
    executor._aggregate_wave_metrics(step_results1, "a" * 4000, messages1, state)
    first_total = state.total_tokens_used

    # Second wave
    messages2 = [
        HumanMessage(content="y" * 8000),
        AIMessage(content="b" * 8000),
    ]
    step_results2 = [
        StepExecutionRecord(
            step_id="step2",
            success=True,
            output="b" * 8000,
            duration_ms=150,
            thread_id="test-thread",
            tool_call_count=2,
            subagent_task_completions=1,
            hit_subagent_cap=False,
        ),
    ]
    executor._aggregate_wave_metrics(step_results2, "b" * 8000, messages2, state)

    # Second wave adds input + output tokens (each ~1000 for 8000 chars)
    # plus structural overhead, so the delta exceeds the old output-only
    # count of 2000.
    delta = state.total_tokens_used - first_total
    assert delta > 2000
    assert state.context_percentage_consumed > 0


def test_aggregate_metrics_sums_multi_hop_ai_usage(mock_core_agent, config, state):
    """Each CoreAgent tool-loop hop contributes to loop token totals."""
    from langchain_core.messages import AIMessage

    executor = Executor(mock_core_agent, config=config)
    messages = [
        AIMessage(
            content="tools",
            usage_metadata={"input_tokens": 8000, "output_tokens": 100, "total_tokens": 8100},
        ),
        AIMessage(
            content="done",
            usage_metadata={"input_tokens": 8100, "output_tokens": 360, "total_tokens": 8460},
        ),
    ]
    step_results = [
        StepExecutionRecord(
            step_id="step1",
            success=True,
            output="done",
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=2,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
    ]

    executor._aggregate_wave_metrics(step_results, "done", messages, state)

    assert state.total_tokens_used == 8100 + 8460


def test_aggregate_metrics_multiple_cap_hits(mock_core_agent, config, state):
    """OR logic for cap hit across multiple steps."""
    executor = Executor(mock_core_agent, config=config)

    step_results = [
        StepExecutionRecord(
            step_id="step1",
            success=True,
            output="Output 1",
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=1,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
        StepExecutionRecord(
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


def test_aggregate_metrics_no_double_counting_with_actual_usage(mock_core_agent, config, state):
    """IG-761: when actual usage_metadata is present, no estimated counts are added."""
    from langchain_core.messages import AIMessage, HumanMessage

    executor = Executor(mock_core_agent, config=config)
    # Human prompt is large; AI carries real usage_metadata.
    messages = [
        HumanMessage(content="x" * 100_000),
        AIMessage(
            content="done",
            usage_metadata={"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050},
        ),
    ]
    step_results = [
        StepExecutionRecord(
            step_id="step1",
            success=True,
            output="done",
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=0,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
    ]

    executor._aggregate_wave_metrics(step_results, "done", messages, state)

    # Actual-first: only the real 1050 tokens are counted. The large human
    # prompt is NOT re-estimated on top (no double-counting).
    assert state.total_tokens_used == 1050


def test_aggregate_metrics_estimates_input_and_output_on_fallback(mock_core_agent, config, state):
    """IG-761: fallback estimates BOTH input and output, not output alone."""
    from langchain_core.messages import AIMessage, HumanMessage

    executor = Executor(mock_core_agent, config=config)
    # No usage_metadata → estimation path.
    messages = [
        HumanMessage(content="prompt " * 200),  # sizable input
        AIMessage(content="response " * 200),  # sizable output
    ]
    step_results = [
        StepExecutionRecord(
            step_id="step1",
            success=True,
            output="response " * 200,
            duration_ms=100,
            thread_id="test-thread",
            tool_call_count=0,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        ),
    ]

    executor._aggregate_wave_metrics(step_results, "response " * 200, messages, state)

    # Output-only count would be ~the tokens of "response "*200. The new
    # behavior adds input tokens too, so total must strictly exceed an
    # output-only estimate.
    from soothe_nano.utils.token_counting import count_tokens

    output_only = count_tokens("response " * 200)
    assert state.total_tokens_used > output_only
    assert state.total_tokens_used > 0
