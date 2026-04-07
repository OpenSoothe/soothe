"""Tests for conditional prior conversation injection in Reason prompt (IG-133)."""

import pytest

from soothe.backends.planning.simple import build_loop_reason_prompt
from soothe.cognition.loop_agent.schemas import LoopState
from soothe.config import SootheConfig
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
def context_with_recent_messages():
    """PlanContext with recent messages."""
    return PlanContext(
        goal="Test goal",
        thread_id="test-thread",
        workspace=None,
        git_status=None,
        recent_messages=[
            "User: Previous message 1",
            "Assistant: Previous response 1",
            "User: Previous message 2",
            "Assistant: Previous response 2",
        ],
    )


def test_prior_conversation_injected_when_no_checkpoint_access(config, state, context_with_recent_messages):
    """Prior conversation is injected when Act won't have checkpoint access."""
    state.act_will_have_checkpoint_access = False

    prompt = build_loop_reason_prompt("Test goal", state, context_with_recent_messages, config=config)

    assert "<SOOTHE_PRIOR_CONVERSATION>" in prompt
    assert "Previous message 1" in prompt
    assert "Previous response 1" in prompt
    assert "<SOOTHE_FOLLOW_UP_POLICY>" in prompt


def test_prior_conversation_not_injected_when_checkpoint_access(config, state, context_with_recent_messages):
    """Prior conversation is NOT injected when Act will have checkpoint access."""
    state.act_will_have_checkpoint_access = True

    prompt = build_loop_reason_prompt("Test goal", state, context_with_recent_messages, config=config)

    assert "<SOOTHE_PRIOR_CONVERSATION>" not in prompt
    assert "Previous message 1" not in prompt
    assert "Previous response 1" not in prompt


def test_no_injection_when_empty_recent_messages(config, state):
    """No injection when recent_messages is empty, regardless of flag."""
    context_empty = PlanContext(
        goal="Test goal",
        thread_id="test-thread",
        workspace=None,
        git_status=None,
        recent_messages=[],
    )

    state.act_will_have_checkpoint_access = False
    prompt = build_loop_reason_prompt("Test goal", state, context_empty, config=config)

    assert "<SOOTHE_PRIOR_CONVERSATION>" not in prompt


def test_prior_conversation_format(config, state, context_with_recent_messages):
    """Prior conversation section is properly formatted."""
    state.act_will_have_checkpoint_access = False

    prompt = build_loop_reason_prompt("Test goal", state, context_with_recent_messages, config=config)

    # Check structure
    assert "Recent messages in this thread before the current goal" in prompt
    assert "The user may refer to this content" in prompt
    assert "<SOOTHE_FOLLOW_UP_POLICY>" in prompt
    assert 'status MUST NOT be "done"' in prompt
    assert "</SOOTHE_PRIOR_CONVERSATION>" in prompt


def test_flag_true_prevents_duplication(config, state, context_with_recent_messages):
    """Flag=True prevents duplication with checkpoint history."""
    state.act_will_have_checkpoint_access = True

    prompt = build_loop_reason_prompt("Test goal", state, context_with_recent_messages, config=config)

    # Verify no prior conversation section
    assert "<SOOTHE_PRIOR_CONVERSATION>" not in prompt

    # This means CoreAgent will load messages from checkpoint instead
    # Reason prompt is leaner, avoiding duplication


def test_flag_false_enables_context_for_isolated_execution(config, state, context_with_recent_messages):
    """Flag=False enables prior context for isolated execution."""
    state.act_will_have_checkpoint_access = False

    prompt = build_loop_reason_prompt("Test goal", state, context_with_recent_messages, config=config)

    # Prior conversation is present
    assert "<SOOTHE_PRIOR_CONVERSATION>" in prompt

    # This ensures isolated threads (no checkpoint) still have prior context
    # Critical for follow-up tasks like "translate that"
