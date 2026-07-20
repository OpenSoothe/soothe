"""Tests for IG-355 delegate-final text aggregation from ``task`` tool returns."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from soothe.foundation.sloop.engine.executor import Executor
from soothe.foundation.sloop.engine.step_wave_types import _StreamCollectChunk


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
    final = rows[-1]
    assert final.output is not None
    assert final.delegate_final.strip() == "Namespaced explore answer."
    assert final.main_tool_count == 0
    assert final.subgraph_tool_count == 1


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
    final = results[-1]
    assert final.event is None
    assert final.output is not None
    assert final.main_tool_count == 1
    assert final.delegate_final == "Counted 3 README files."
    assert "Counted 3 README files." in final.output


@pytest.mark.asyncio
async def test_record_execute_wave_prefers_delegate_final_over_empty_root_ai() -> None:
    """LoopState receives delegate text when root-graph AIMessage list is empty."""
    from soothe.foundation.sloop.state.schemas import LoopState

    mock_agent = MagicMock()
    executor = Executor(mock_agent)
    state = LoopState(goal="test", thread_id="tid")
    executor._record_execute_wave_for_finalize(
        state,
        [],
        parallel_multi_step=False,
        delegate_final_text="Final from task tool.",
    )
    assert state.last_wave_answer_from_delegate_final is True


def test_record_execute_wave_parallel_multi_merges_delegate_finals() -> None:
    """Parallel multi-step waves preserve merged delegate text for goal completion (IG-356)."""
    from soothe.foundation.sloop.state.schemas import LoopState

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
    event = modified_chunk.event
    assert event is not None
    if len(event) == 3:
        _ns, mode, data = event
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
    modified_chunk = rows[0]
    event = modified_chunk.event
    assert event is not None
    _ns, mode, data = event
    assert mode == "messages"
    msg = data[0]
    tc_chunks = getattr(msg, "tool_call_chunks", None) or []
    assert tc_chunks[0]["id"].startswith("GHT_01:t0:")


@pytest.mark.asyncio
async def test_stream_and_collect_rewrites_tool_call_id_to_unified() -> None:
    """Provider tool_call_ids are rewritten to unified format for namespaced chunks."""
    from langchain_core.messages import AIMessageChunk

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
    rewritten_msg: AIMessageChunk | None = None
    async for chunk in executor._stream_and_collect(
        fake_stream(),
        budget=None,
        step_id="GHT-01",
    ):
        event = chunk.event
        # Rewritten message is in event tuple for intermediate yields (not in msgs)
        if isinstance(event, tuple) and len(event) == 3:
            ns, mode, data = event
            if mode == "messages" and isinstance(data, tuple) and len(data) >= 1:
                msg = data[0]
                if isinstance(msg, AIMessageChunk) and msg.tool_calls:
                    rewritten_msg = msg

    # Verify tool_call_id was rewritten to unified format
    # The provider id "functions.grep:0" becomes "GHT_01:t0:grep:0" (task-level since namespaced)
    assert rewritten_msg is not None
    assert len(rewritten_msg.tool_calls) == 1
    tc = rewritten_msg.tool_calls[0]
    # Unified format: {step_wire}:{type}:{tool}:{idx} where step_wire uses underscore
    assert tc["id"] == "GHT_01:t0:grep:0"
    assert tc["name"] == "grep"
    assert tc["args"] == {"pattern": "TODO"}


@pytest.mark.asyncio
async def test_backfill_tool_calls_args_from_chunks_by_index() -> None:
    """Chunks without ``id`` still backfill ``tool_calls`` via ``index``."""
    from langchain_core.messages import AIMessage

    from soothe.foundation.sloop.engine.executor import _backfill_tool_calls_args_from_chunks

    msg = AIMessage(
        content="",
        tool_calls=[{"name": "task", "args": {}, "id": "call-1", "type": "tool_call"}],
        tool_call_chunks=[
            {
                "index": 0,
                "args": {
                    "description": "Indexed chunk args",
                    "subagent_type": "deep_research",
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
            step_description="Map goal engine to sloop boundaries",
            step_subagent="deep_research",
        )
    ]
    event = rows[0].event
    assert event is not None
    _ns, _mode, data = event
    msg = data[0]
    tc = msg.tool_calls[0]
    assert tc["id"] == "JPV_01:s:task:0"
    assert "sloop" in str(tc["args"].get("description", ""))
    assert tc["args"].get("subagent_type") == "deep_research"


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
                            "subagent_type": "deep_research",
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
            step_subagent="deep_research",
        )
    ]
    event = rows[0].event
    assert event is not None
    msg = event[2][0]
    assert msg.tool_calls[0]["args"]["description"] == "Model-specific delegation brief"


@pytest.mark.asyncio
async def test_stream_emits_string_tool_call_chunk_args_after_enrich() -> None:
    """Wire-safe stream: chunk args are JSON strings, not dicts."""
    import json

    from langchain_core.messages import AIMessageChunk

    chunk_args = json.dumps(
        {"description": "From chunks", "subagent_type": "deep_research"},
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
            step_subagent="deep_research",
        )
    ]
    event = rows[0].event
    assert event is not None
    msg = event[2][0]
    tc_chunks = getattr(msg, "tool_call_chunks", None) or []
    assert tc_chunks
    assert isinstance(tc_chunks[0]["args"], str)
    assert "description" in tc_chunks[0]["args"]


@pytest.mark.asyncio
async def test_backfill_tool_calls_args_from_chunks_on_same_message() -> None:
    """Terminal AIMessage with empty tool_calls gets args from tool_call_chunks."""
    from langchain_core.messages import AIMessage

    from soothe.foundation.sloop.engine.executor import _backfill_tool_calls_args_from_chunks

    msg = AIMessage(
        content="",
        tool_calls=[{"name": "task", "args": {}, "id": "call-1", "type": "tool_call"}],
        tool_call_chunks=[
            {
                "name": "task",
                "args": {
                    "description": "Explore the repo",
                    "subagent_type": "deep_research",
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
                        "args": '{"subagent_type": "deep_research"}',
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
    event = rows[0].event
    assert event is not None
    _ns, _mode, data = event
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
    wire = rows[0]
    event = wire.event
    assert isinstance(event, tuple) and len(event) == 3
    _ns, mode, data = event
    assert mode == "messages"
    msg = data[0]
    assert isinstance(msg, ToolMessage)
    assert msg.tool_call_id == "GHT_01:s:grep:0"


@pytest.mark.asyncio
async def test_stream_and_collect_logs_tool_call_args_from_index_chunk(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tool kwargs from index-only chunks appear in debug logs after id rewrite."""
    from langchain_core.messages import AIMessageChunk

    ai = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "index": 0,
                "name": "read_file",
                "args": '{"file_path": "/tmp/foo.txt"}',
            },
        ],
    )
    tool_msg = ToolMessage(
        content="hello",
        tool_call_id="functions.read_file:0",
        name="read_file",
    )

    async def fake_stream():
        yield ((), "messages", (ai, {}))
        yield ((), "messages", (tool_msg, {}))

    executor = Executor(MagicMock())
    caplog.set_level(logging.DEBUG, logger="soothe.foundation.sloop.engine.executor")
    async for _row in executor._stream_and_collect(
        fake_stream(),
        budget=None,
        step_id="STP-01",
    ):
        pass

    assert any(
        "read_file" in rec.message and "file_path" in rec.message and "/tmp/foo.txt" in rec.message
        for rec in caplog.records
        if rec.levelname == "DEBUG" and "[Tool#" in rec.message
    )


@pytest.mark.asyncio
async def test_stream_and_collect_emits_late_tool_call_update_on_tool_message() -> None:
    """Wire update is emitted on ToolMessage when args were recorded from index chunks."""
    from langchain_core.messages import AIMessageChunk
    from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

    ai = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "index": 3,
                "name": "edit_file",
                "args": '{"file_path": "README.md"}',
            },
        ],
    )
    tool_msg = ToolMessage(
        content="ok",
        tool_call_id="functions.edit_file:3",
        name="edit_file",
    )

    async def fake_stream():
        yield ((), "messages", (ai, {}))
        yield ((), "messages", (tool_msg, {}))

    executor = Executor(MagicMock())
    custom_payloads: list[dict] = []
    async for chunk in executor._stream_and_collect(
        fake_stream(),
        budget=None,
        step_id="YJH-01",
    ):
        event = chunk.event
        if isinstance(event, tuple) and len(event) == 3 and event[1] == "custom":  # noqa: PLR2004
            data = event[2]
            if isinstance(data, dict):
                custom_payloads.append(data)

    assert any(
        p.get("type") == STREAM_TOOL_CALL_UPDATE
        and p.get("tool_call_id") == "YJH_01:s:edit_file:3"
        and p.get("args", {}).get("file_path") == "README.md"
        for p in custom_payloads
    )


@pytest.mark.asyncio
async def test_stream_and_collect_counts_execute_namespace_tool_message() -> None:
    """Execute-namespace ToolMessages must count toward main_tool_count (RFC-628)."""
    from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

    ai = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "functions.wizsearch_search:0",
                "name": "wizsearch_search",
                "args": {"query": "world cup teams"},
            }
        ],
    )
    tool_msg = ToolMessage(
        content="search results here",
        tool_call_id="functions.wizsearch_search:0",
        name="wizsearch_search",
    )
    execute_ns = ("execute:00019ed6-dfca-2758-204b-dae1a999a6ca",)

    async def fake_stream():
        yield (execute_ns, "messages", (ai, {}))
        yield (execute_ns, "messages", (tool_msg, {}))

    executor = Executor(MagicMock())
    custom_payloads: list[dict] = []
    final = None
    async for chunk in executor._stream_and_collect(
        fake_stream(),
        budget=None,
        step_id="EMV-b4a35046",
    ):
        event = chunk.event
        if isinstance(event, tuple) and len(event) == 3 and event[1] == "custom":  # noqa: PLR2004
            data = event[2]
            if isinstance(data, dict):
                custom_payloads.append(data)
        if chunk.output is not None:
            final = chunk

    assert final is not None
    assert final.main_tool_count == 1
    assert "search results here" in (final.output or "")
    assert any(
        p.get("type") == STREAM_TOOL_CALL_UPDATE
        and p.get("tool_call_id") == "EMV_b4a35046:s:wizsearch_search:0"
        and p.get("args", {}).get("query") == "world cup teams"
        for p in custom_payloads
    )


@pytest.mark.asyncio
async def test_stream_and_collect_logs_tool_call_args_from_invocation_registry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tool kwargs come from middleware invocation registry when stream has no AI chunks."""
    from langchain.agents.middleware.types import ToolCallRequest

    # IG-519: Use registry directly (semaphore removed from stack)
    from soothe_nano.middleware.tool_call_args_registry import (
        get_recorded_tool_call_args,
        init_tool_call_args_registry,
        record_tool_call_args_from_request,
    )

    init_tool_call_args_registry()
    registry_key = "functions.read_file:0"
    record_tool_call_args_from_request(
        ToolCallRequest(
            tool_call={
                "id": registry_key,
                "name": "read_file",
                "args": {"file_path": "/tmp/foo.txt"},
            },
            tool=None,
            state={"messages": []},
            runtime=MagicMock(),
        )
    )

    tool_msg = ToolMessage(
        content="hello",
        tool_call_id=registry_key,
        name="read_file",
    )

    async def fake_stream():
        yield ((), "messages", (tool_msg, {}))

    executor = Executor(MagicMock())
    caplog.set_level(logging.DEBUG, logger="soothe.foundation.sloop.engine.executor")
    async for _row in executor._stream_and_collect(
        fake_stream(),
        budget=None,
        step_id="STP-01",
    ):
        pass

    assert get_recorded_tool_call_args(registry_key)["file_path"] == "/tmp/foo.txt"
    assert any(
        "read_file" in rec.message and "file_path" in rec.message and "/tmp/foo.txt" in rec.message
        for rec in caplog.records
        if rec.levelname == "DEBUG" and "[Tool#" in rec.message
    )


@pytest.mark.asyncio
async def test_stream_and_collect_logs_tool_call_args(caplog: pytest.LogCaptureFixture) -> None:
    """Tool outcome debug log includes kwargs recorded from the preceding AI tool_calls."""
    ai = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "functions.read_file:0",
                "name": "read_file",
                "args": {"path": "/tmp/foo.txt"},
            }
        ],
    )
    tool_msg = ToolMessage(
        content="hello",
        tool_call_id="functions.read_file:0",
        name="read_file",
    )

    async def fake_stream():
        yield ((), "messages", (ai, {}))
        yield ((), "messages", (tool_msg, {}))

    executor = Executor(MagicMock())
    caplog.set_level(logging.DEBUG, logger="soothe.foundation.sloop.engine.executor")
    async for _row in executor._stream_and_collect(
        fake_stream(),
        budget=None,
        step_id="STP-01",
    ):
        pass

    assert any(
        "read_file" in rec.message and 'args={"path": "/tmp/foo.txt"}' in rec.message
        for rec in caplog.records
        if rec.levelname == "DEBUG"
    )


@pytest.mark.asyncio
async def test_stream_and_collect_logs_write_todos_update(caplog: pytest.LogCaptureFixture) -> None:
    """write_todos tool calls emit a dedicated todo-list debug log during step execution."""
    todos = [
        {"content": "Survey docs", "status": "in_progress"},
        {"content": "Fix errors", "status": "pending"},
    ]
    ai = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "functions.write_todos:0",
                "name": "write_todos",
                "args": {"todos": todos},
            }
        ],
    )
    tool_msg = ToolMessage(
        content="Updated todo list",
        tool_call_id="functions.write_todos:0",
        name="write_todos",
    )

    async def fake_stream():
        yield ((), "messages", (ai, {}))
        yield ((), "messages", (tool_msg, {}))

    executor = Executor(MagicMock())
    caplog.set_level(logging.DEBUG, logger="soothe.foundation.sloop.engine.executor")
    async for _row in executor._stream_and_collect(
        fake_stream(),
        budget=None,
        step_id="STP-01",
    ):
        pass

    assert any(
        "[write_todos]" in rec.message
        and "step=STP-01" in rec.message
        and "[in_progress] Survey docs" in rec.message
        and "[pending] Fix errors" in rec.message
        for rec in caplog.records
        if rec.levelname == "DEBUG"
    )


@pytest.mark.asyncio
async def test_stream_and_collect_assigns_task_idx_per_subgraph_namespace() -> None:
    """Parallel ``task:0`` and ``task:1`` subgraphs stamp ``t0`` / ``t1`` inner tool ids."""
    from langchain_core.messages import AIMessageChunk

    main_task_chunk: tuple = (
        (),
        "messages",
        (
            AIMessageChunk(
                content="",
                tool_calls=[
                    {"name": "task", "args": {}, "id": "functions.task:0"},
                    {"name": "task", "args": {}, "id": "functions.task:1"},
                ],
            ),
            {},
        ),
    )
    subgraph_a: tuple = (
        ("tools:subgraph-a",),
        "messages",
        (
            AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": "grep", "id": "functions.grep:0", "args": "{}"}],
            ),
            {},
        ),
    )
    subgraph_b: tuple = (
        ("tools:subgraph-b",),
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
        yield main_task_chunk
        yield subgraph_a
        yield subgraph_b

    executor = Executor(mock_agent)
    rewritten_ids: list[str] = []
    async for chunk in executor._stream_and_collect(
        fake_stream(),
        budget=None,
        step_id="WAV-01",
    ):
        event = chunk.event
        if not isinstance(event, tuple) or len(event) != 3:
            continue
        _ns, mode, data = event
        if mode != "messages" or not isinstance(data, tuple):
            continue
        msg = data[0]
        if not isinstance(msg, AIMessageChunk):
            continue
        for tc in getattr(msg, "tool_call_chunks", None) or []:
            if isinstance(tc, dict) and tc.get("id"):
                rewritten_ids.append(str(tc["id"]))

    assert "WAV_01:t0:grep:0" in rewritten_ids
    assert "WAV_01:t1:grep:0" in rewritten_ids


@pytest.mark.asyncio
async def test_stream_and_collect_emits_subgraph_placeholder_wire_update() -> None:
    """Subagent ``tools:`` subgraph placeholder updates yield wire chunks (ea1d regression)."""
    from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

    tool_msg = ToolMessage(
        content="[]",
        tool_call_id="functions.glob:0",
        name="glob",
    )
    chunk: tuple = (
        ("tools:subgraph-explore",),
        "messages",
        (tool_msg, {}),
    )
    mock_agent = MagicMock()

    async def fake_stream():
        yield chunk

    executor = Executor(mock_agent)
    wire_chunks: list[_StreamCollectChunk] = []
    async for chunk_out in executor._stream_and_collect(
        fake_stream(),
        budget=None,
        step_id="JNA-02",
    ):
        if chunk_out.event is not None and chunk_out.event[1] == "custom":
            wire_chunks.append(chunk_out)

    assert wire_chunks
    payload = wire_chunks[0].event[2]
    assert isinstance(payload, dict)
    assert payload.get("type") == STREAM_TOOL_CALL_UPDATE
    assert str(payload.get("tool_call_id", "")).startswith("JNA_02:t0:glob:")


def test_record_execute_wave_parallel_multi_clears_when_no_delegate() -> None:
    """Parallel wave with no task returns keeps assistant text empty."""
    from soothe.foundation.sloop.state.schemas import LoopState

    mock_agent = MagicMock()
    executor = Executor(mock_agent)
    state = LoopState(goal="test", thread_id="tid")
    executor._record_execute_wave_for_finalize(
        state,
        [],
        parallel_multi_step=True,
        delegate_final_text=None,
    )
    assert state.last_wave_answer_from_delegate_final is False
