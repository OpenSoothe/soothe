"""Tests for metrics section in Reason prompt (IG-132)."""

import pytest

from soothe.cognition.loop_agent.schemas import LoopState
from soothe.config import SootheConfig
from soothe.core.prompts import PromptBuilder
from soothe.protocols.planner import PlanContext


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
        iteration=1,
        max_iterations=8,
    )


@pytest.fixture
def context():
    """PlanContext for testing."""
    return PlanContext(
        goal="Test goal",
        thread_id="test-thread",
        workspace=None,
        git_status=None,
        recent_messages=[],
    )


def test_metrics_section_included_when_wave_executed(config, state, context):
    """Metrics section appears when last_wave_tool_call_count > 0."""
    state.last_wave_tool_call_count = 2
    state.last_wave_subagent_task_count = 1
    state.last_wave_output_length = 8000
    state.last_wave_error_count = 0
    state.last_wave_hit_subagent_cap = False
    state.total_tokens_used = 30000
    state.context_percentage_consumed = 0.15

    builder = PromptBuilder(config)
    prompt = builder.build_reason_prompt("Test goal", state, context)

    assert "<SOOTHE_WAVE_METRICS>" in prompt
    assert "Subagent calls: 1" in prompt
    assert "Tool calls: 2" in prompt
    assert "Output length: 8,000 characters" in prompt
    assert "Errors: 0" in prompt
    assert "Cap hit: No" in prompt
    assert "Context used: 15.0%" in prompt
    assert "30,000 tokens" in prompt


def test_metrics_section_omitted_when_no_wave(config, state, context):
    """Metrics section not included when last_wave_tool_call_count == 0."""
    state.last_wave_tool_call_count = 0

    builder = PromptBuilder(config)
    prompt = builder.build_reason_prompt("Test goal", state, context)

    assert "<SOOTHE_WAVE_METRICS>" not in prompt


def test_metrics_section_cap_hit_yes(config, state, context):
    """Metrics section shows cap hit status correctly."""
    state.last_wave_tool_call_count = 1
    state.last_wave_hit_subagent_cap = True

    builder = PromptBuilder(config)
    prompt = builder.build_reason_prompt("Test goal", state, context)

    assert "Cap hit: Yes" in prompt


def test_metrics_section_no_context_data(config, state, context):
    """Metrics section handles missing context window data."""
    state.last_wave_tool_call_count = 1
    state.total_tokens_used = 0
    state.context_percentage_consumed = 0.0

    builder = PromptBuilder(config)
    prompt = builder.build_reason_prompt("Test goal", state, context)

    assert "Context used: N/A" in prompt
    assert "N/A tokens" in prompt


def test_metrics_section_large_numbers_formatted(config, state, context):
    """Metrics section formats large numbers with commas."""
    state.last_wave_tool_call_count = 15
    state.last_wave_output_length = 125000
    state.total_tokens_used = 150000

    builder = PromptBuilder(config)
    prompt = builder.build_reason_prompt("Test goal", state, context)

    assert "Output length: 125,000 characters" in prompt
    assert "150,000 tokens" in prompt


def test_metrics_section_with_errors(config, state, context):
    """Metrics section includes error count."""
    state.last_wave_tool_call_count = 3
    state.last_wave_error_count = 2

    builder = PromptBuilder(config)
    prompt = builder.build_reason_prompt("Test goal", state, context)

    assert "Errors: 2" in prompt


def test_metrics_section_position_in_prompt(config, state, context):
    """Metrics section appears after goal and iteration info."""
    state.last_wave_tool_call_count = 1

    builder = PromptBuilder(config)
    prompt = builder.build_reason_prompt("Test goal", state, context)

    # Find positions
    goal_pos = prompt.find("Goal: Test goal")
    iteration_pos = prompt.find("Loop iteration:")
    metrics_pos = prompt.find("<SOOTHE_WAVE_METRICS>")

    # Metrics should come after goal and iteration
    assert goal_pos < iteration_pos < metrics_pos


def test_metrics_section_all_components_present(config, state, context):
    """All metrics components are present in section."""
    state.last_wave_tool_call_count = 5
    state.last_wave_subagent_task_count = 2
    state.last_wave_output_length = 10000
    state.last_wave_error_count = 1
    state.last_wave_hit_subagent_cap = False
    state.total_tokens_used = 50000
    state.context_percentage_consumed = 0.25

    builder = PromptBuilder(config)
    prompt = builder.build_reason_prompt("Test goal", state, context)

    # Check all required fields are present
    required_fields = [
        "Subagent calls:",
        "Tool calls:",
        "Output length:",
        "Errors:",
        "Cap hit:",
        "Context used:",
    ]

    for field in required_fields:
        assert field in prompt, f"Missing field: {field}"
