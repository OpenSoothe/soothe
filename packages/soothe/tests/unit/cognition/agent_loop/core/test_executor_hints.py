"""Unit tests for Executor hint passing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.cognition.agent_loop.core.executor import Executor
from soothe.cognition.agent_loop.state.schemas import StepAction


class TestExecutorHints:
    """Test Executor passes Layer 2 hints to CoreAgent."""

    @pytest.mark.asyncio
    async def test_executor_passes_tools_hint(self):
        """Test Executor passes tools hint via config."""
        # Create mock CoreAgent
        mock_agent = MagicMock()
        mock_agent.astream = AsyncMock(return_value=iter([]))

        # Create executor
        executor = Executor(mock_agent)

        # Create step with tools hint
        step = StepAction(
            id="step-1",
            description="Find config files",
            tools=["glob", "grep"],
            expected_output="Config file list",
        )

        # Execute step
        await executor._execute_step_collecting_events(step, "thread-123")

        # Verify agent.astream was called with hints in config
        mock_agent.astream.assert_called_once()
        call_args = mock_agent.astream.call_args

        assert "config" in call_args.kwargs
        config = call_args.kwargs["config"]
        assert "configurable" in config

        configurable = config["configurable"]
        assert configurable["thread_id"] == "thread-123"
        assert configurable["soothe_step_tools"] == ["glob", "grep"]
        assert configurable["soothe_step_expected_output"] == "Config file list"

    @pytest.mark.asyncio
    async def test_executor_passes_subagent_hint(self):
        """Test Executor passes subagent hint via config."""
        mock_agent = MagicMock()
        mock_agent.astream = AsyncMock(return_value=iter([]))

        executor = Executor(mock_agent)

        step = StepAction(
            id="step-1",
            description="Browse web page",
            subagent="browser",
            expected_output="Page content",
        )

        await executor._execute_step_collecting_events(step, "thread-456")

        call_args = mock_agent.astream.call_args
        configurable = call_args.kwargs["config"]["configurable"]

        assert configurable["soothe_step_subagent"] == "browser"

    @pytest.mark.asyncio
    async def test_executor_passes_expected_output(self):
        """Test Executor passes expected_output hint via config."""
        mock_agent = MagicMock()
        mock_agent.astream = AsyncMock(return_value=iter([]))

        executor = Executor(mock_agent)

        step = StepAction(
            id="step-1",
            description="Read config",
            expected_output="Config contents",
        )

        await executor._execute_step_collecting_events(step, "thread-789")

        call_args = mock_agent.astream.call_args
        configurable = call_args.kwargs["config"]["configurable"]

        assert configurable["soothe_step_expected_output"] == "Config contents"

    @pytest.mark.asyncio
    async def test_executor_handles_missing_hints(self):
        """Test Executor handles steps without hints."""
        mock_agent = MagicMock()
        mock_agent.astream = AsyncMock(return_value=iter([]))

        executor = Executor(mock_agent)

        step = StepAction(
            id="step-1",
            description="Read file",
            expected_output="File contents",
        )
        # tools and subagent are None

        await executor._execute_step_collecting_events(step, "thread-000")

        call_args = mock_agent.astream.call_args
        configurable = call_args.kwargs["config"]["configurable"]

        # Should still pass the hints (as None values)
        assert configurable["soothe_step_tools"] is None
        assert configurable["soothe_step_subagent"] is None
        assert configurable["soothe_step_expected_output"] == "File contents"

    @pytest.mark.asyncio
    async def test_executor_logs_hints(self, caplog):
        """Test Executor logs hint information."""
        mock_agent = MagicMock()
        mock_agent.astream = AsyncMock(return_value=iter([]))

        executor = Executor(mock_agent)

        step = StepAction(
            id="step-1",
            description="Find files",
            tools=["glob", "grep"],
            expected_output="File list",
        )

        await executor._execute_step_collecting_events(step, "thread-123")

        # Check debug log contains hints
        assert "tools=['glob', 'grep']" in caplog.text
        assert "subagent=None" in caplog.text
