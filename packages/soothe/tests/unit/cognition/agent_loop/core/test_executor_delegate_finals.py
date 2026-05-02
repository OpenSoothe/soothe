"""Tests for IG-355 delegate-final text aggregation from ``task`` tool returns."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage

from soothe.cognition.agent_loop.core.executor import Executor


@pytest.mark.asyncio
async def test_stream_and_collect_joins_task_tool_returns_as_delegate_finals() -> None:
    """``task`` ToolMessage bodies become delegate_final_text (ordered, capped elsewhere)."""
    tool_msg = ToolMessage(
        content="Counted 3 README files.",
        tool_call_id="call_task_1",
        name="task",
    )
    chunk: tuple = (
        (),
        "messages",
        (tool_msg, {}),
    )

    mock_agent = MagicMock()

    async def fake_stream():
        yield chunk

    executor = Executor(mock_agent)
    results = []
    async for row in executor._stream_and_collect(fake_stream(), budget=None):
        results.append(row)
    assert len(results) == 2  # tuple passthrough + final aggregate
    final_out, event, tc_count, msgs, delegate_final = results[-1]
    assert event is None
    assert tc_count == 1
    assert delegate_final == "Counted 3 README files."
    assert "Counted 3 README files." in (final_out or "")


@pytest.mark.asyncio
async def test_record_execute_wave_prefers_delegate_final_over_empty_root_ai() -> None:
    """LoopState receives delegate text when root-graph AIMessage list is empty."""
    from soothe.cognition.agent_loop.state.schemas import LoopState

    mock_agent = MagicMock()
    executor = Executor(mock_agent)
    state = LoopState(goal="test", thread_id="tid")
    executor._record_execute_wave_for_finalize(
        state,
        [],
        parallel_multi_step=False,
        delegate_final_text="Final from task tool.",
    )
    assert state.last_execute_assistant_text == "Final from task tool."
    assert state.last_wave_answer_from_delegate_final is True
