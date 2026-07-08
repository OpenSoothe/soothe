"""Tests for execute action retry via the step deliverable gate."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from soothe.foundation.sloop.cognition.step_deliverable import TRIVIAL_DIRECT_EXPECTED_OUTPUT
from soothe.foundation.sloop.engine.executor import Executor
from soothe.foundation.sloop.engine.step_wave_types import _StreamCollectChunk
from soothe.foundation.sloop.state.schemas import StepAction


async def _empty_async_gen(*_args: Any, **_kwargs: Any) -> AsyncIterator[Any]:
    if False:  # pragma: no cover
        yield


class TestExecutorActionRetry:
    @pytest.mark.asyncio
    async def test_retries_when_first_pass_is_narration_only(self) -> None:
        mock_agent = MagicMock()
        mock_agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
        mock_agent.execution_aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.can_read_graph_state = False

        executor = Executor(mock_agent)
        call_count = 0

        async def fake_stream_and_collect(
            _stream: Any, **kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield _StreamCollectChunk.finalized(
                    output="Let me fetch that information for you.",
                    main_tool_count=0,
                    messages=[AIMessage(content="Let me fetch that information for you.")],
                    delegate_final="",
                    outcomes=[],
                    has_error=False,
                    subgraph_tool_count=0,
                )
            else:
                yield _StreamCollectChunk.finalized(
                    output="Shanghai: sunny, 22°C",
                    main_tool_count=1,
                    messages=[
                        AIMessage(content="Shanghai: sunny, 22°C"),
                    ],
                    delegate_final="",
                    outcomes=[{"type": "code_exec", "tool_name": "run_command"}],
                    has_error=False,
                    subgraph_tool_count=0,
                )

        step = StepAction(
            id="step-1",
            description="weather shanghai get for me",
            expected_output=TRIVIAL_DIRECT_EXPECTED_OUTPUT,
            requires_tool_use=True,
        )

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            result = await executor._execute_step_collecting_events(step, "thread-weather")

        assert call_count == 2
        assert result.step_result is not None
        assert result.step_result.tool_call_count == 1
        assert "Shanghai" in (result.output or "")

    @pytest.mark.asyncio
    async def test_no_retry_when_tools_and_answer_on_first_pass(self) -> None:
        mock_agent = MagicMock()
        mock_agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
        mock_agent.execution_aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.can_read_graph_state = False

        executor = Executor(mock_agent)
        call_count = 0

        async def fake_stream_and_collect(
            _stream: Any, **kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            nonlocal call_count
            call_count += 1
            yield _StreamCollectChunk.finalized(
                output="The weather in Shanghai is sunny, 22°C.",
                main_tool_count=1,
                messages=[
                    AIMessage(content="The weather in Shanghai is sunny, 22°C."),
                ],
                delegate_final="",
                outcomes=[{"type": "code_exec", "tool_name": "run_command", "has_error": False}],
                has_error=False,
                subgraph_tool_count=0,
            )

        step = StepAction(
            id="step-1",
            description="weather shanghai",
            expected_output=TRIVIAL_DIRECT_EXPECTED_OUTPUT,
            requires_tool_use=True,
        )

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            result = await executor._execute_step_collecting_events(step, "thread-weather")

        assert call_count == 1
        assert result.step_result is not None
        assert result.step_result.tool_call_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_for_reasoning_without_tools(self) -> None:
        mock_agent = MagicMock()
        mock_agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
        mock_agent.execution_aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.can_read_graph_state = False

        executor = Executor(mock_agent)
        call_count = 0

        async def fake_stream_and_collect(
            _stream: Any, **kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            nonlocal call_count
            call_count += 1
            yield _StreamCollectChunk.finalized(
                output="Answer: 4",
                main_tool_count=0,
                messages=[AIMessage(content="Answer: 4")],
                delegate_final="",
                outcomes=[],
                has_error=False,
                subgraph_tool_count=0,
            )

        step = StepAction(
            id="step-1",
            description="what is 2+2",
            expected_output=TRIVIAL_DIRECT_EXPECTED_OUTPUT,
            requires_tool_use=False,
        )

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            result = await executor._execute_step_collecting_events(step, "thread-math")

        assert call_count == 1
        assert result.step_result is not None
        assert result.step_result.tool_call_count == 0

    @pytest.mark.asyncio
    async def test_retry_replaces_prior_pass_output(self) -> None:
        mock_agent = MagicMock()
        mock_agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
        mock_agent.execution_aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.aget_state = AsyncMock(return_value=MagicMock())
        mock_agent.can_read_graph_state = False

        executor = Executor(mock_agent)
        call_count = 0

        async def fake_stream_and_collect(
            _stream: Any, **kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield _StreamCollectChunk.finalized(
                    output="Let me fetch...",
                    main_tool_count=0,
                    messages=[AIMessage(content="Let me fetch...")],
                    delegate_final="",
                    outcomes=[],
                    has_error=False,
                    subgraph_tool_count=0,
                )
            else:
                yield _StreamCollectChunk.finalized(
                    output="Shanghai: sunny",
                    main_tool_count=1,
                    messages=[AIMessage(content="Shanghai: sunny")],
                    delegate_final="",
                    outcomes=[
                        {"type": "code_exec", "tool_name": "run_command", "has_error": False}
                    ],
                    has_error=False,
                    subgraph_tool_count=0,
                )

        step = StepAction(
            id="step-1",
            description="weather shanghai",
            expected_output=TRIVIAL_DIRECT_EXPECTED_OUTPUT,
            requires_tool_use=True,
        )

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            result = await executor._execute_step_collecting_events(step, "thread-weather")

        assert result.output == "Shanghai: sunny"
        assert "Let me fetch" not in (result.output or "")
