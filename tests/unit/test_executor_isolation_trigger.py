"""Tests for automatic isolation trigger logic in Executor (IG-132)."""

import pytest

from soothe.cognition.loop_agent.executor import Executor
from soothe.cognition.loop_agent.schemas import StepAction
from soothe.config import SootheConfig


@pytest.fixture
def mock_core_agent():
    """Mock CoreAgent for testing."""

    class MockCoreAgent:
        pass

    return MockCoreAgent()


@pytest.fixture
def config_enabled():
    """Config with isolation enabled."""
    return SootheConfig(
        agentic={
            "sequential_act_isolated_thread": True,
        }
    )


@pytest.fixture
def config_disabled():
    """Config with isolation disabled."""
    return SootheConfig(
        agentic={
            "sequential_act_isolated_thread": False,
        }
    )


def test_isolation_trigger_with_subagent(mock_core_agent, config_enabled):
    """Isolation enabled when step has subagent delegation."""
    executor = Executor(mock_core_agent, config=config_enabled)

    steps = [
        StepAction(
            description="Translate to Chinese",
            subagent="claude",
            expected_output="Chinese translation",
        )
    ]

    assert executor._should_use_isolated_sequential_thread(steps) is True


def test_isolation_trigger_without_subagent(mock_core_agent, config_enabled):
    """Isolation disabled when step is tool-only."""
    executor = Executor(mock_core_agent, config=config_enabled)

    steps = [
        StepAction(
            description="Execute command",
            tools=["run_command"],
            expected_output="Command output",
        )
    ]

    assert executor._should_use_isolated_sequential_thread(steps) is False


def test_isolation_trigger_mixed_steps(mock_core_agent, config_enabled):
    """Isolation enabled when any step has subagent."""
    executor = Executor(mock_core_agent, config=config_enabled)

    steps = [
        StepAction(
            description="Execute command",
            tools=["run_command"],
            expected_output="Command output",
        ),
        StepAction(
            description="Translate result",
            subagent="claude",
            expected_output="Translated output",
        ),
    ]

    assert executor._should_use_isolated_sequential_thread(steps) is True


def test_isolation_trigger_config_disabled(mock_core_agent, config_disabled):
    """Isolation disabled when config flag is False, even with subagent."""
    executor = Executor(mock_core_agent, config=config_disabled)

    steps = [
        StepAction(
            description="Translate to Chinese",
            subagent="claude",
            expected_output="Chinese translation",
        )
    ]

    assert executor._should_use_isolated_sequential_thread(steps) is False


def test_isolation_trigger_multiple_subagents(mock_core_agent, config_enabled):
    """Isolation enabled with multiple subagent steps."""
    executor = Executor(mock_core_agent, config=config_enabled)

    steps = [
        StepAction(
            description="Research topic",
            subagent="research",
            expected_output="Research results",
        ),
        StepAction(
            description="Summarize findings",
            subagent="claude",
            expected_output="Summary",
        ),
    ]

    assert executor._should_use_isolated_sequential_thread(steps) is True


def test_isolation_trigger_no_config(mock_core_agent):
    """Isolation disabled when no config provided."""
    executor = Executor(mock_core_agent, config=None)

    steps = [
        StepAction(
            description="Translate to Chinese",
            subagent="claude",
            expected_output="Chinese translation",
        )
    ]

    assert executor._should_use_isolated_sequential_thread(steps) is False
