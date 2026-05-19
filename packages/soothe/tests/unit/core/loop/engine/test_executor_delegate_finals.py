"""Tests for IG-355 delegate-final text aggregation from ``task`` tool returns."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage

from soothe.core.loop.engine.executor import Executor


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
    _evt, _ev, tc_total, _msgs, delegate_final = rows[-1]
    assert delegate_final.strip() == "Namespaced explore answer."
    assert tc_total == 1  # namespaced ``task`` ToolMessage counts toward wave tool total


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
    from soothe.core.loop.state.schemas import LoopState

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
    from soothe.core.loop.state.schemas import LoopState

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


@pytest.mark.asyncio
async def test_stream_and_collect_rewrites_tool_call_ids_to_unified() -> None:
    """Root AI tool-call ids are rewritten to unified format with step_id prefix."""
    from langchain_core.messages import AIMessageChunk

    chunk: tuple = (
        (),
        "messages",
        (
            AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": "grep", "id": "functions.grep:0", "args": "{}"}],
            ),
            {},
        ),
    )
    mock_agent = MagicMock()

    async def fake_stream():
        yield chunk

    executor = Executor(mock_agent)
    rows: list = []
    async for row in executor._stream_and_collect(
        fake_stream(),
        budget=None,
        step_id="GHT-01",
    ):
        rows.append(row)
    # Should have the modified chunk (unified IDs)
    assert len(rows) >= 1
    # Check that the chunk was modified with unified ID
    modified_chunk = rows[0]
    if isinstance(modified_chunk[1], tuple) and len(modified_chunk[1]) == 3:
        _ns, mode, data = modified_chunk[1]
        if mode == "messages" and isinstance(data, tuple) and len(data) >= 2:
            msg = data[0]
            if isinstance(msg, AIMessageChunk):
                tc_chunks = getattr(msg, "tool_call_chunks", None) or []
                if tc_chunks:
                    tc_id = tc_chunks[0].get("id", "")
                    # Unified format: {step_id}:s:{tool}.{idx}
                    assert tc_id.startswith("GHT_01:s:")


@pytest.mark.asyncio
async def test_stream_and_collect_rewrites_subgraph_tool_ids_to_task_level() -> None:
    """Namespaced AI tool-call ids use ``{step_id}:t{idx}:…`` for TUI binding."""
    from langchain_core.messages import AIMessageChunk

    chunk: tuple = (
        ("tools:subgraph-1",),
        "messages",
        (
            AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": "grep", "id": "functions.grep:0", "args": "{}"}],
            ),
            {},
        ),
    )
    mock_agent = MagicMock()

    async def fake_stream():
        yield chunk

    executor = Executor(mock_agent)
    rows = [
        r
        async for r in executor._stream_and_collect(
            fake_stream(),
            budget=None,
            step_id="GHT-01",
        )
    ]
    modified_chunk = rows[0][1]
    _ns, mode, data = modified_chunk
    assert mode == "messages"
    msg = data[0]
    tc_chunks = getattr(msg, "tool_call_chunks", None) or []
    assert tc_chunks[0]["id"].startswith("GHT_01:t0:")


@pytest.mark.asyncio
async def test_stream_and_collect_emits_tool_call_update_custom_events() -> None:
    """Namespaced tool kwargs are also sent as ``soothe.stream.tool_call.update`` events."""
    from langchain_core.messages import AIMessageChunk
    from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

    chunk: tuple = (
        ("tools:subgraph-1",),
        "messages",
        (
            AIMessageChunk(
                content="",
                tool_calls=[{"name": "grep", "args": {}, "id": "functions.grep:0"}],
                tool_call_chunks=[
                    {
                        "name": "grep",
                        "id": "functions.grep:0",
                        "args": '{"pattern": "TODO"}',
                    },
                ],
            ),
            {},
        ),
    )
    mock_agent = MagicMock()

    async def fake_stream():
        yield chunk

    executor = Executor(mock_agent)
    custom_payloads: list[dict] = []
    async for _out, event, _tc, _msgs, _df in executor._stream_and_collect(
        fake_stream(),
        budget=None,
        step_id="GHT-01",
    ):
        if isinstance(event, tuple) and len(event) == 3 and event[1] == "custom":  # noqa: PLR2004
            data = event[2]
            if isinstance(data, dict):
                custom_payloads.append(data)

    assert any(
        p.get("type") == STREAM_TOOL_CALL_UPDATE
        and p.get("tool_call_id", "").startswith("GHT_01:t0:grep")
        and p.get("args", {}).get("pattern") == "TODO"
        for p in custom_payloads
    )


@pytest.mark.asyncio
async def test_backfill_tool_calls_args_from_chunks_by_index() -> None:
    """Chunks without ``id`` still backfill ``tool_calls`` via ``index``."""
    from langchain_core.messages import AIMessage

    from soothe.core.loop.engine.executor import _backfill_tool_calls_args_from_chunks

    msg = AIMessage(
        content="",
        tool_calls=[{"name": "task", "args": {}, "id": "call-1", "type": "tool_call"}],
        tool_call_chunks=[
            {
                "index": 0,
                "args": {
                    "description": "Indexed chunk args",
                    "subagent_type": "explore",
                },
            },
        ],
    )
    out = _backfill_tool_calls_args_from_chunks(msg)
    assert out.tool_calls[0]["args"]["description"] == "Indexed chunk args"


@pytest.mark.asyncio
async def test_stream_injects_step_description_on_empty_task_args() -> None:
    """Main-graph ``task`` with ``{}`` args receives execute-step description on the wire."""
    from langchain_core.messages import AIMessageChunk

    chunk: tuple = (
        (),
        "messages",
        (
            AIMessageChunk(
                content="",
                tool_calls=[{"name": "task", "args": {}, "id": "functions.task:0"}],
            ),
            {},
        ),
    )
    mock_agent = MagicMock()

    async def fake_stream():
        yield chunk

    executor = Executor(mock_agent)
    rows = [
        r
        async for r in executor._stream_and_collect(
            fake_stream(),
            budget=None,
            step_id="JPV-01",
            step_description="Map goal engine to agentloop boundaries",
            step_subagent="explore",
        )
    ]
    _ns, _mode, data = rows[0][1]
    msg = data[0]
    tc = msg.tool_calls[0]
    assert tc["id"] == "JPV_01:s:task:0"
    assert "agentloop" in str(tc["args"].get("description", ""))
    assert tc["args"].get("subagent_type") == "explore"


@pytest.mark.asyncio
async def test_stream_preserves_model_task_description_over_step_brief() -> None:
    """Model-provided ``description`` is not replaced by the execute-step brief."""
    from langchain_core.messages import AIMessageChunk

    chunk: tuple = (
        (),
        "messages",
        (
            AIMessageChunk(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "description": "Model-specific delegation brief",
                            "subagent_type": "explore",
                        },
                        "id": "functions.task:0",
                    }
                ],
            ),
            {},
        ),
    )
    mock_agent = MagicMock()

    async def fake_stream():
        yield chunk

    executor = Executor(mock_agent)
    rows = [
        r
        async for r in executor._stream_and_collect(
            fake_stream(),
            budget=None,
            step_id="JPV-02",
            step_description="Step plan text only",
            step_subagent="explore",
        )
    ]
    msg = rows[0][1][2][0]
    assert msg.tool_calls[0]["args"]["description"] == "Model-specific delegation brief"


@pytest.mark.asyncio
async def test_stream_emits_string_tool_call_chunk_args_after_enrich() -> None:
    """Wire-safe stream: chunk args are JSON strings, not dicts."""
    import json

    from langchain_core.messages import AIMessageChunk

    chunk_args = json.dumps(
        {"description": "From chunks", "subagent_type": "explore"},
        separators=(",", ":"),
    )
    chunk: tuple = (
        (),
        "messages",
        (
            AIMessageChunk(
                content="",
                tool_calls=[{"name": "task", "args": {}, "id": "functions.task:0"}],
                tool_call_chunks=[
                    {
                        "name": "task",
                        "id": "functions.task:0",
                        "args": chunk_args,
                    }
                ],
            ),
            {},
        ),
    )
    mock_agent = MagicMock()

    async def fake_stream():
        yield chunk

    executor = Executor(mock_agent)
    rows = [
        r
        async for r in executor._stream_and_collect(
            fake_stream(),
            budget=None,
            step_id="WAA-04",
            step_description="Step fallback brief",
            step_subagent="explore",
        )
    ]
    msg = rows[0][1][2][0]
    tc_chunks = getattr(msg, "tool_call_chunks", None) or []
    assert tc_chunks
    assert isinstance(tc_chunks[0]["args"], str)
    assert "description" in tc_chunks[0]["args"]


@pytest.mark.asyncio
async def test_backfill_tool_calls_args_from_chunks_on_same_message() -> None:
    """Terminal AIMessage with empty tool_calls gets args from tool_call_chunks."""
    from langchain_core.messages import AIMessage

    from soothe.core.loop.engine.executor import _backfill_tool_calls_args_from_chunks

    msg = AIMessage(
        content="",
        tool_calls=[{"name": "task", "args": {}, "id": "call-1", "type": "tool_call"}],
        tool_call_chunks=[
            {
                "name": "task",
                "args": {
                    "description": "Explore the repo",
                    "subagent_type": "explore",
                },
                "id": "call-1",
            },
        ],
    )
    out = _backfill_tool_calls_args_from_chunks(msg)
    assert out.tool_calls[0]["args"]["description"] == "Explore the repo"


@pytest.mark.asyncio
async def test_subgraph_rewrite_skips_already_unified_step_level_ids() -> None:
    """Subgraph stream must not double-prefix step-level unified task ids."""
    from langchain_core.messages import AIMessageChunk

    chunk: tuple = (
        ("tools:subgraph-1",),
        "messages",
        (
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "task",
                        "id": "EZJ_07:s:task:0",
                        "args": '{"subagent_type": "explore"}',
                    },
                ],
            ),
            {},
        ),
    )
    mock_agent = MagicMock()

    async def fake_stream():
        yield chunk

    executor = Executor(mock_agent)
    rows = [
        r
        async for r in executor._stream_and_collect(
            fake_stream(),
            budget=None,
            step_id="EZJ-07",
        )
    ]
    _ns, _mode, data = rows[0][1]
    msg = data[0]
    tc_chunks = getattr(msg, "tool_call_chunks", None) or []
    assert tc_chunks[0]["id"] == "EZJ_07:s:task:0"


@pytest.mark.asyncio
async def test_stream_and_collect_rewrites_root_tool_message_to_unified_id() -> None:
    """Root ToolMessage.tool_call_id matches rewritten AI ids for TUI result binding (IG-416)."""
    tool_msg = ToolMessage(
        content="done",
        tool_call_id="functions.grep:0",
        name="grep",
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
    rows: list = []
    async for row in executor._stream_and_collect(
        fake_stream(),
        budget=None,
        step_id="GHT-01",
    ):
        rows.append(row)
    assert len(rows) >= 2
    _out, event, _tc, _msgs, _df = rows[0]
    assert isinstance(event, tuple) and len(event) == 3
    _ns, mode, data = event
    assert mode == "messages"
    msg = data[0]
    assert isinstance(msg, ToolMessage)
    assert msg.tool_call_id == "GHT_01:s:grep:0"


def test_record_execute_wave_parallel_multi_clears_when_no_delegate() -> None:
    """Parallel wave with no task returns keeps assistant text empty."""
    from soothe.core.loop.state.schemas import LoopState

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
