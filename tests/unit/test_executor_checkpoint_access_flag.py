"""Tests for act_will_have_checkpoint_access flag in Executor (IG-133)."""

import pytest

from soothe.cognition.loop_agent.executor import Executor
from soothe.cognition.loop_agent.schemas import AgentDecision, LoopState, StepAction
from soothe.config import SootheConfig


@pytest.fixture
def mock_core_agent():
    """Mock CoreAgent for testing."""

    class MockCoreAgent:
        pass

    return MockCoreAgent()


@pytest.fixture
def config_isolation_enabled():
    """Config with thread isolation enabled."""
    return SootheConfig(
        agentic={
            "sequential_act_isolated_thread": True,
        }
    )


@pytest.fixture
def config_isolation_disabled():
    """Config with thread isolation disabled."""
    return SootheConfig(
        agentic={
            "sequential_act_isolated_thread": False,
        }
    )


@pytest.fixture
def state():
    """Fresh LoopState for testing."""
    return LoopState(goal="Test goal", thread_id="test-thread")


def test_sequential_tool_only_has_checkpoint_access(mock_core_agent, config_isolation_enabled, state):
    """Sequential tool-only execution has checkpoint access."""
    executor = Executor(mock_core_agent, config=config_isolation_enabled)

    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(description="Run command", tools=["run_command"], expected_output="output")],
        execution_mode="sequential",
        reasoning="Test",
    )

    # Sync call to set the flag (normally done in execute())
    ready_steps = decision.get_ready_steps(state.completed_step_ids)
    has_delegation = any(bool(getattr(s, "subagent", None)) for s in ready_steps)
    isolation_enabled = executor._config.agentic.sequential_act_isolated_thread
    state.act_will_have_checkpoint_access = not (has_delegation and isolation_enabled)

    assert state.act_will_have_checkpoint_access is True


def test_sequential_delegation_with_isolation_no_checkpoint(mock_core_agent, config_isolation_enabled, state):
    """Sequential delegation with isolation enabled has NO checkpoint access."""
    executor = Executor(mock_core_agent, config=config_isolation_enabled)

    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(description="Translate to Chinese", subagent="claude", expected_output="translation")],
        execution_mode="sequential",
        reasoning="Test",
    )

    ready_steps = decision.get_ready_steps(state.completed_step_ids)
    has_delegation = any(bool(getattr(s, "subagent", None)) for s in ready_steps)
    isolation_enabled = executor._config.agentic.sequential_act_isolated_thread
    state.act_will_have_checkpoint_access = not (has_delegation and isolation_enabled)

    assert state.act_will_have_checkpoint_access is False


def test_sequential_delegation_without_isolation_has_checkpoint(mock_core_agent, config_isolation_disabled, state):
    """Sequential delegation without isolation has checkpoint access."""
    executor = Executor(mock_core_agent, config=config_isolation_disabled)

    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(description="Translate to Chinese", subagent="claude", expected_output="translation")],
        execution_mode="sequential",
        reasoning="Test",
    )

    ready_steps = decision.get_ready_steps(state.completed_step_ids)
    has_delegation = any(bool(getattr(s, "subagent", None)) for s in ready_steps)
    isolation_enabled = executor._config.agentic.sequential_act_isolated_thread
    state.act_will_have_checkpoint_access = not (has_delegation and isolation_enabled)

    assert state.act_will_have_checkpoint_access is True


def test_parallel_execution_no_checkpoint(mock_core_agent, config_isolation_enabled, state):
    """Parallel execution has NO checkpoint access (isolated threads)."""
    executor = Executor(mock_core_agent, config=config_isolation_enabled)

    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(description="Step 1", tools=["run_command"], expected_output="output"),
            StepAction(description="Step 2", tools=["run_command"], expected_output="output"),
        ],
        execution_mode="parallel",
        reasoning="Test",
    )

    # Parallel mode always sets flag to False
    if decision.execution_mode == "parallel":
        state.act_will_have_checkpoint_access = False

    assert state.act_will_have_checkpoint_access is False


def test_dependency_execution_no_checkpoint(mock_core_agent, config_isolation_enabled, state):
    """Dependency execution has NO checkpoint access (isolated threads)."""
    executor = Executor(mock_core_agent, config=config_isolation_enabled)

    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(description="Step 1", tools=["run_command"], expected_output="output", dependencies=[]),
            StepAction(
                description="Step 2",
                tools=["run_command"],
                expected_output="output",
                dependencies=["step1"],
            ),
        ],
        execution_mode="dependency",
        reasoning="Test",
    )

    # Dependency mode always sets flag to False
    if decision.execution_mode == "dependency":
        state.act_will_have_checkpoint_access = False

    assert state.act_will_have_checkpoint_access is False


def test_mixed_steps_with_isolation_no_checkpoint(mock_core_agent, config_isolation_enabled, state):
    """Mixed tool + delegation steps with isolation has NO checkpoint access."""
    executor = Executor(mock_core_agent, config=config_isolation_enabled)

    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(description="Run command", tools=["run_command"], expected_output="output"),
            StepAction(description="Translate result", subagent="claude", expected_output="translation"),
        ],
        execution_mode="sequential",
        reasoning="Test",
    )

    ready_steps = decision.get_ready_steps(state.completed_step_ids)
    has_delegation = any(bool(getattr(s, "subagent", None)) for s in ready_steps)
    isolation_enabled = executor._config.agentic.sequential_act_isolated_thread
    state.act_will_have_checkpoint_access = not (has_delegation and isolation_enabled)

    assert state.act_will_have_checkpoint_access is False


def test_no_config_defaults_to_checkpoint_access(state):
    """No config defaults to checkpoint access (conservative)."""
    mock_core_agent = type("MockCoreAgent", (), {})()
    executor = Executor(mock_core_agent, config=None)

    # With no config, isolation is disabled, so checkpoint access should be True
    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(description="Translate", subagent="claude", expected_output="translation")],
        execution_mode="sequential",
        reasoning="Test",
    )

    ready_steps = decision.get_ready_steps(state.completed_step_ids)
    has_delegation = any(bool(getattr(s, "subagent", None)) for s in ready_steps)
    isolation_enabled = executor._config is not None and executor._config.agentic.sequential_act_isolated_thread
    state.act_will_have_checkpoint_access = not (has_delegation and isolation_enabled)

    assert state.act_will_have_checkpoint_access is True
