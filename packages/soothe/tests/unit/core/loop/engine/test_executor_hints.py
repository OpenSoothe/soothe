"""Unit tests for Executor hint passing."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.loop.engine.executor import Executor
from soothe.foundation.loop.state.schemas import AgentDecision, LoopState, StepAction


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
    async def test_executor_passes_wire_subagent_hint(self):
        """Test Executor passes wire preferred_subagent via config when routing_hint=subagent."""
        mock_agent = MagicMock()
        mock_agent.astream = AsyncMock(return_value=iter([]))

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

        call_args = mock_agent.astream.call_args
        configurable = call_args.kwargs["config"]["configurable"]

        assert configurable["soothe_step_subagent"] == "explore"
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
            expected_output="File list",
        )
        routing = {"routing_hint": "subagent", "preferred_subagent": "explore"}

        await executor._execute_step_collecting_events(
            step, "thread-123", routing_classification=routing
        )

        assert "wire_subagent=explore" in caplog.text

    @pytest.mark.asyncio
    async def test_executor_thread_fork_creates_isolated_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A no-deps step gets a fresh isolated ``__step_<id>`` thread (RFC-223).

        The fork goes through the in-house ``copy_thread_via_public_api`` helper
        (LangGraph savers don't implement ``acopy_thread``).
        """
        from soothe.foundation.loop.engine import thread_fork_manager as tfm_mod

        copy_calls: list[tuple[str, str]] = []

        async def _fake_copy(saver: Any, source: str, target: str) -> int:
            copy_calls.append((source, target))
            return 0

        monkeypatch.setattr(tfm_mod, "copy_thread_via_public_api", _fake_copy)

        mock_agent = MagicMock()
        mock_agent.astream = AsyncMock(return_value=iter([]))
        mock_checkpointer = MagicMock()

        executor = Executor(mock_agent, checkpointer=mock_checkpointer)
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

        _events, step_result, _msgs, _df = await executor._execute_step_collecting_events(
            step,
            "logical-thread",
            loop_state=state,
        )

        call_args = mock_agent.astream.call_args
        configurable = call_args.kwargs["config"]["configurable"]
        # ThreadForkManager creates __step_ prefixed thread
        assert configurable["thread_id"] == "logical-thread__step_a1b2c3d4"
        assert step_result.thread_id == "logical-thread"
        # Verify fork copy was invoked once via the in-house helper.
        assert copy_calls == [("logical-thread", "logical-thread__step_a1b2c3d4")]

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
