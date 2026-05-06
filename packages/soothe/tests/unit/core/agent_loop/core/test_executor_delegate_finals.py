"""Tests for IG-355 delegate-final text aggregation from ``task`` tool returns."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage

from soothe.core.agent_loop.execution.executor import Executor


@pytest.mark.asyncio
async def test_stream_and_collect_namespaced_task_chunk_populates_delegate_finals() -> None:
    """Namespaced ``messages`` chunk carries Explore subgraph ``task`` return (IG-355)."""
    tool_msg = ToolMessage(
        content="Namespaced explore answer.",
        tool_call_id="call_ns_task",
        name="task",
    )
    chunk_ns: tuple = (
        ("functions.task:0",),
        "messages",
        (tool_msg, {}),
    )

    mock_agent = MagicMock()

    async def fake_stream():
        yield chunk_ns

    executor = Executor(mock_agent)
    rows = [r async for r in executor._stream_and_collect(fake_stream(), budget=None)]
    _evt, _ev, _tc, _msgs, delegate_final = rows[-1]
    assert delegate_final.strip() == "Namespaced explore answer."


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
    from soothe.core.agent_loop.state.schemas import LoopState

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


def test_record_execute_wave_parallel_multi_merges_delegate_finals() -> None:
    """Parallel multi-step waves preserve merged delegate text for goal completion (IG-356)."""
    from soothe.core.agent_loop.state.schemas import LoopState

    mock_agent = MagicMock()
    executor = Executor(mock_agent)
    state = LoopState(goal="test", thread_id="tid")
    merged = "First delegate.\n\n---\n\nSecond delegate."
    executor._record_execute_wave_for_finalize(
        state,
        [],
        parallel_multi_step=True,
        delegate_final_text=merged,
    )
    assert state.last_execute_assistant_text == merged
    assert state.last_wave_answer_from_delegate_final is True


def test_record_execute_wave_parallel_multi_clears_when_no_delegate() -> None:
    """Parallel wave with no task returns keeps assistant text empty."""
    from soothe.core.agent_loop.state.schemas import LoopState

    mock_agent = MagicMock()
    executor = Executor(mock_agent)
    state = LoopState(goal="test", thread_id="tid")
    executor._record_execute_wave_for_finalize(
        state,
        [],
        parallel_multi_step=True,
        delegate_final_text=None,
    )
    assert state.last_execute_assistant_text is None
    assert state.last_wave_answer_from_delegate_final is False
