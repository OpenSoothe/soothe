"""Unit tests for Executor hint passing."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.sloop.engine.executor import Executor
from soothe.foundation.sloop.state.schemas import AgentDecision, LoopState, StepAction


async def _empty_async_gen(*_args: Any, **_kwargs: Any) -> AsyncIterator[Any]:
    """Empty async generator for mocking agent.execution_astream."""
    if False:  # pragma: no cover - never yields
        yield


class TestExecutorHints:
    """Test Executor passes Layer 2 hints to CoreAgent."""

    @pytest.mark.asyncio
    async def test_executor_omits_legacy_tools_config_key(self):
        """Executor does not set soothe_step_tools (IG-382)."""
        mock_agent = MagicMock()
        # execution_astream is sync and returns an async iterator — not awaitable.
        mock_agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
        mock_agent.execution_aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.aget_state = AsyncMock(return_value=MagicMock())

        executor = Executor(mock_agent)

        step = StepAction(
            id="step-1",
            description="Find config files",
            expected_output="Config file list",
        )

        await executor._execute_step_collecting_events(step, "thread-123")

        mock_agent.execution_astream.assert_called_once()
        call_args = mock_agent.execution_astream.call_args
        config = call_args.kwargs["config"]
        configurable = config["configurable"]

        assert configurable["thread_id"] == "thread-123"
        assert "soothe_step_tools" not in configurable
        assert configurable["soothe_step_expected_output"] == "Config file list"

    @pytest.mark.asyncio
    async def test_executor_passes_wire_subagent_hint(self):
        """Test Executor passes wire preferred_subagent via config when routing_hint=subagent."""
        mock_agent = MagicMock()
        # execution_astream is sync and returns an async iterator — not awaitable.
        mock_agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
        mock_agent.execution_aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.aget_state = AsyncMock(return_value=MagicMock())

        executor = Executor(mock_agent)

        step = StepAction(
            id="step-1",
            description="Map repository layout",
            expected_output="Matching paths",
        )
        routing = {"routing_hint": "subagent", "preferred_subagent": "explore"}

        await executor._execute_step_collecting_events(
            step, "thread-456", routing_classification=routing
        )

        call_args = mock_agent.execution_astream.call_args
        configurable = call_args.kwargs["config"]["configurable"]

        assert configurable["soothe_step_subagent"] == "explore"
        assert "soothe_step_tools" not in configurable

    @pytest.mark.asyncio
    async def test_executor_passes_step_wire_subagent_from_planner(self):
        """Planner execution_hint=subagent flows to soothe_step_subagent."""
        mock_agent = MagicMock()
        mock_agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
        mock_agent.execution_aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.aget_state = AsyncMock(return_value=MagicMock())

        executor = Executor(mock_agent)

        step = StepAction(
            id="step-1",
            description="Map repository layout",
            expected_output="Matching paths",
            execution_hint="subagent",
            subagent="explore",
            wire_subagent="explore",
        )

        await executor._execute_step_collecting_events(step, "thread-456")

        configurable = mock_agent.execution_astream.call_args.kwargs["config"]["configurable"]
        assert configurable["soothe_step_subagent"] == "explore"

    @pytest.mark.asyncio
    async def test_executor_passes_expected_output(self):
        """Test Executor passes expected_output hint via config."""
        mock_agent = MagicMock()
        # execution_astream is sync and returns an async iterator — not awaitable.
        mock_agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
        mock_agent.execution_aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.aget_state = AsyncMock(return_value=MagicMock())

        executor = Executor(mock_agent)

        step = StepAction(
            id="step-1",
            description="Read config",
            expected_output="Config contents",
        )

        await executor._execute_step_collecting_events(step, "thread-789")

        call_args = mock_agent.execution_astream.call_args
        configurable = call_args.kwargs["config"]["configurable"]

        assert configurable["soothe_step_expected_output"] == "Config contents"

    @pytest.mark.asyncio
    async def test_executor_handles_missing_hints(self):
        """Test Executor handles steps without optional hints."""
        mock_agent = MagicMock()
        # execution_astream is sync and returns an async iterator — not awaitable.
        mock_agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
        mock_agent.execution_aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.aget_state = AsyncMock(return_value=MagicMock())

        executor = Executor(mock_agent)

        step = StepAction(
            id="step-1",
            description="Read file",
            expected_output="File contents",
        )

        await executor._execute_step_collecting_events(step, "thread-000")

        call_args = mock_agent.execution_astream.call_args
        configurable = call_args.kwargs["config"]["configurable"]

        assert "soothe_step_tools" not in configurable
        assert configurable["soothe_step_subagent"] is None
        assert configurable["soothe_step_expected_output"] == "File contents"

    @pytest.mark.asyncio
    async def test_executor_logs_hints(self, caplog):
        """Test Executor logs hint information."""
        import logging

        caplog.set_level(logging.DEBUG)
        mock_agent = MagicMock()
        # execution_astream is sync and returns an async iterator — not awaitable.
        mock_agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
        mock_agent.execution_aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.aget_state = AsyncMock(return_value=MagicMock())

        executor = Executor(mock_agent)

        step = StepAction(
            id="step-1",
            description="Find files",
            expected_output="File list",
        )
        routing = {"routing_hint": "subagent", "preferred_subagent": "explore"}

        await executor._execute_step_collecting_events(
            step, "thread-123", routing_classification=routing
        )

        assert "wire_subagent=explore" in caplog.text

    @pytest.mark.asyncio
    async def test_executor_thread_creates_isolated_thread(self) -> None:
        """A no-deps step gets a fresh isolated ``__step_<id>`` thread (IG-477).

        No checkpoint fork — thread isolation for parallel safety, predecessor
        context arrives via message injection.
        """
        mock_agent = MagicMock()
        # execution_astream is sync and returns an async iterator — not awaitable.
        mock_agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
        mock_agent.execution_aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.aget_state = AsyncMock(return_value=MagicMock())

        executor = Executor(mock_agent)
        step = StepAction(id="a1b2c3d4", description="Explore slice", expected_output="ok")
        state = LoopState(
            goal="test",
            thread_id="logical-thread",
            current_decision=AgentDecision(
                type="execute_steps",
                steps=[step],
                execution_mode="parallel",
                reasoning="test",
            ),
            loop_messages=[],
        )

        result = await executor._execute_step_collecting_events(
            step,
            "logical-thread",
            loop_state=state,
        )

        call_args = mock_agent.execution_astream.call_args
        configurable = call_args.kwargs["config"]["configurable"]
        # IG-477: creates __step_ prefixed thread for isolation
        assert configurable["thread_id"] == "logical-thread__step_a1b2c3d4"
        assert result.step_result.thread_id == "logical-thread"
        assert state.step_thread_ids["a1b2c3d4"] == "logical-thread__step_a1b2c3d4"

    @pytest.mark.asyncio
    async def test_executor_step_cancelled_error_propagates(self) -> None:
        """Cancellation should stop step execution immediately."""

        async def _cancel_stream():
            raise asyncio.CancelledError
            if False:
                yield None  # pragma: no cover

        mock_agent = MagicMock()
        mock_agent.execution_astream = MagicMock(return_value=_cancel_stream())
        executor = Executor(mock_agent)
        step = StepAction(
            id="step-cancel", description="Run cancellable step", expected_output="n/a"
        )

        with pytest.raises(asyncio.CancelledError):
            await executor._execute_step_collecting_events(step, "thread-cancel")
