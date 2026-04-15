"""Tests for metrics section in Plan prompt.

Note: RFC-207 removed wave metrics from Plan prompts.
Wave metrics are now internal tracking only (logged by LLMTracingMiddleware).
"""

import pytest

from soothe.cognition.agent_loop.schemas import LoopState
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


def test_metrics_section_removed_rfc207(config, state, context):
    """RFC-207: Wave metrics section no longer included in prompts."""
    state.last_wave_tool_call_count = 2
    state.last_wave_subagent_task_count = 1
    state.last_wave_output_length = 8000
    state.last_wave_error_count = 0
    state.last_wave_hit_subagent_cap = False
    state.total_tokens_used = 30000
    state.context_percentage_consumed = 0.15

    builder = PromptBuilder(config)
    prompt = builder.build_plan_prompt("Test goal", state, context)

    # RFC-207: Wave metrics removed from prompts (internal tracking only)
    assert "<SOOTHE_WAVE_METRICS>" not in prompt
    assert "Subagent calls:" not in prompt
    assert "Tool calls:" not in prompt
    assert "Output length:" not in prompt
    assert "Errors:" not in prompt
    assert "Cap hit:" not in prompt
    assert "Context used:" not in prompt


def test_last_act_wave_metrics_removed_rfc207(config, state, context):
    """RFC-207: Last Act wave metrics section also removed."""
    state.last_wave_tool_call_count = 1
    state.last_wave_subagent_task_count = 1

    builder = PromptBuilder(config)
    prompt = builder.build_plan_prompt("Test goal", state, context)

    # RFC-207: Last Act wave metrics removed from prompts
    assert "<SOOTHE_LAST_ACT_WAVE_METRICS>" not in prompt
