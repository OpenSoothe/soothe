"""Unit tests for Executor hint passing."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.core.loop.engine.executor import Executor
from soothe.core.loop.state.schemas import StepAction


class TestExecutorHints:
    """Test Executor passes Layer 2 hints to CoreAgent."""

    @pytest.mark.asyncio
    async def test_executor_omits_legacy_tools_config_key(self):
        """Executor does not set soothe_step_tools (IG-382)."""
        mock_agent = MagicMock()
        mock_agent.astream = AsyncMock(return_value=iter([]))

        executor = Executor(mock_agent)

        step = StepAction(
            id="step-1",
            description="Find config files",
            expected_output="Config file list",
        )

        await executor._execute_step_collecting_events(step, "thread-123")

        mock_agent.astream.assert_called_once()
        call_args = mock_agent.astream.call_args
        config = call_args.kwargs["config"]
        configurable = config["configurable"]

        assert configurable["thread_id"] == "thread-123"
        assert "soothe_step_tools" not in configurable
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
        assert "soothe_step_tools" not in configurable

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
        """Test Executor handles steps without optional hints."""
        mock_agent = MagicMock()
        mock_agent.astream = AsyncMock(return_value=iter([]))

        executor = Executor(mock_agent)

        step = StepAction(
            id="step-1",
            description="Read file",
            expected_output="File contents",
        )

        await executor._execute_step_collecting_events(step, "thread-000")

        call_args = mock_agent.astream.call_args
        configurable = call_args.kwargs["config"]["configurable"]

        assert "soothe_step_tools" not in configurable
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
            subagent="explore",
            expected_output="File list",
        )

        await executor._execute_step_collecting_events(step, "thread-123")

        assert "subagent=explore" in caplog.text

    @pytest.mark.asyncio
    async def test_executor_stream_thread_id_branches_langgraph_config(self) -> None:
        """Parallel steps pass branched thread_id into configurable for checkpoint isolation."""
        mock_agent = MagicMock()
        mock_agent.astream = AsyncMock(return_value=iter([]))

        executor = Executor(mock_agent)
        step = StepAction(id="a1b2c3d4", description="Explore slice", expected_output="ok")

        _events, step_result, _msgs, _df = await executor._execute_step_collecting_events(
            step,
            "logical-thread",
            stream_thread_id="logical-thread__pa1b2c3d4",
        )

        call_args = mock_agent.astream.call_args
        configurable = call_args.kwargs["config"]["configurable"]
        assert configurable["thread_id"] == "logical-thread__pa1b2c3d4"
        assert step_result.thread_id == "logical-thread"

    @pytest.mark.asyncio
    async def test_executor_step_cancelled_error_propagates(self) -> None:
        """Cancellation should stop step execution immediately."""

        async def _cancel_stream():
            raise asyncio.CancelledError
            if False:
                yield None  # pragma: no cover

        mock_agent = MagicMock()
        mock_agent.astream = MagicMock(return_value=_cancel_stream())
        executor = Executor(mock_agent)
        step = StepAction(
            id="step-cancel", description="Run cancellable step", expected_output="n/a"
        )

        with pytest.raises(asyncio.CancelledError):
            await executor._execute_step_collecting_events(step, "thread-cancel")
