"""Tests for tool-aware dispatch timeout in GraphStreamChunkReader (IG-681).

Covers:
- Deadlock detection (no chunks, no root tool pending)
- Per-wave tool wall-clock cap
- Long tool execution tolerance (idle suppressed while tools pending)
- Parallel tool waves (first ToolMessage must not clear remaining tools)
- Nested subgraph ToolMessages (progress only; do not clear parent)
- Sentinel cap suspended while tools are active
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from soothe.sloop.engine.graph_interrupt import (
    _STREAM_HEARTBEAT_SENTINEL,
    DispatchTimeoutError,
    GraphStreamChunkReader,
    _classify_stream_chunk,
    _detect_tool_boundary,
)

# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


class TestDetectToolBoundary:
    """Unit tests for the chunk classifier."""

    def test_sentinel(self) -> None:
        assert _detect_tool_boundary(_STREAM_HEARTBEAT_SENTINEL) == "sentinel"

    def test_plain_string(self) -> None:
        assert _detect_tool_boundary("hello") == "chunk"

    def test_ai_message_with_tool_calls(self) -> None:
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "run_command", "args": {"command": "ls"}, "id": "c1"}],
        )
        chunk = ((), "messages", [msg, {}])
        assert _detect_tool_boundary(chunk) == "tool_dispatch"
        assert _classify_stream_chunk(chunk).tool_call_ids == ("c1",)

    def test_ai_message_without_tool_calls(self) -> None:
        msg = AIMessage(content="thinking about the problem")
        chunk = ((), "messages", [msg, {}])
        assert _detect_tool_boundary(chunk) == "chunk"

    def test_ai_message_chunk_with_tool_call_chunks(self) -> None:
        msg = AIMessageChunk(
            content="",
            tool_call_chunks=[
                {"name": "run_command", "args": '{"command":', "id": "c1", "index": 0}
            ],
        )
        chunk = ((), "messages", [msg, {}])
        assert _detect_tool_boundary(chunk) == "tool_dispatch"

    def test_ai_message_chunk_without_tool_call_chunks(self) -> None:
        msg = AIMessageChunk(content="partial text")
        chunk = ((), "messages", [msg, {}])
        assert _detect_tool_boundary(chunk) == "chunk"

    def test_tool_message(self) -> None:
        msg = ToolMessage(content="output", tool_call_id="c1")
        chunk = ((), "messages", [msg, {}])
        assert _detect_tool_boundary(chunk) == "tool_result"
        assert _classify_stream_chunk(chunk).result_tool_call_id == "c1"

    def test_custom_event_chunk(self) -> None:
        chunk = ((), "custom", {"type": "step_heartbeat", "step_id": "X"})
        assert _detect_tool_boundary(chunk) == "chunk"

    def test_malformed_tuple(self) -> None:
        assert _detect_tool_boundary(((), "messages")) == "chunk"

    def test_malformed_messages_data_not_list(self) -> None:
        chunk = ((), "messages", "not_a_list")
        assert _detect_tool_boundary(chunk) == "chunk"

    def test_malformed_messages_empty_list(self) -> None:
        chunk = ((), "messages", [])
        assert _detect_tool_boundary(chunk) == "chunk"

    def test_malformed_messages_first_elem_not_message(self) -> None:
        chunk = ((), "messages", ["string_not_message", {}])
        assert _detect_tool_boundary(chunk) == "chunk"

    def test_execute_namespace_is_root_dispatch(self) -> None:
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "grep", "args": {}, "id": "c1"}],
        )
        chunk = (("execute:run-1",), "messages", [msg, {}])
        assert _detect_tool_boundary(chunk) == "tool_dispatch"

    def test_nested_tools_namespace_is_progress_only(self) -> None:
        """Nested subgraph ToolMessage must not classify as root tool_result."""
        msg = ToolMessage(content="nested", tool_call_id="nested-1")
        chunk = (("tools:subagent",), "messages", [msg, {}])
        assert _detect_tool_boundary(chunk) == "chunk"
        assert _classify_stream_chunk(chunk).kind == "chunk"

    def test_nested_tools_dispatch_is_progress_only(self) -> None:
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "read_file", "args": {}, "id": "n1"}],
        )
        chunk = (("execute:run-1", "tools:xyz"), "messages", [msg, {}])
        assert _detect_tool_boundary(chunk) == "chunk"

    def test_parallel_branch_namespace_is_root(self) -> None:
        msg = ToolMessage(content="ok", tool_call_id="c1")
        chunk = (("execute:run-1", "0"), "messages", [msg, {}])
        assert _detect_tool_boundary(chunk) == "tool_result"


# ---------------------------------------------------------------------------
# GraphStreamChunkReader — tool-aware timeout tests
# ---------------------------------------------------------------------------


async def _slow_single_chunk(value: str = "only", delay: float = 5.0) -> AsyncIterator[str]:
    await asyncio.sleep(delay)
    yield value


async def _dispatch_pause_result(
    dispatch: Any,
    pause: float,
    result: Any,
) -> AsyncIterator[Any]:
    """Simulate tool dispatch → pause (tool running) → tool result."""
    yield dispatch
    await asyncio.sleep(pause)
    yield result


async def _emit_sequence(
    items: list[tuple[float, Any]],
) -> AsyncIterator[Any]:
    """Yield (delay_before, chunk) pairs."""
    for delay, chunk in items:
        if delay > 0:
            await asyncio.sleep(delay)
        yield chunk


# --- Deadlock detection (idle_timeout) ---


@pytest.mark.asyncio
async def test_idle_timeout_raises_when_no_tool_active() -> None:
    """Idle timeout fires when no tool is pending and no chunks arrive."""
    reader = GraphStreamChunkReader(
        _slow_single_chunk(delay=10.0),
        idle_timeout=0.4,
        heartbeat_interval=0.2,
        step_id="TST-01",
    )

    with pytest.raises(DispatchTimeoutError) as exc_info:
        while True:
            chunk = await reader.read_next()
            if chunk is _STREAM_HEARTBEAT_SENTINEL:
                continue
            break  # pragma: no cover

    assert exc_info.value.timeout_seconds == 0.4
    assert exc_info.value.step_id == "TST-01"
    assert exc_info.value.reason == "idle"
    assert "deadlock" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_idle_timeout_does_not_fire_during_tool_execution() -> None:
    """Idle timeout must NOT fire while a root tool is pending."""
    dispatch_msg = AIMessage(
        content="",
        tool_calls=[{"name": "run_command", "args": {"command": "ls"}, "id": "c1"}],
    )
    result_msg = ToolMessage(content="output", tool_call_id="c1")
    dispatch_chunk = ((), "messages", [dispatch_msg, {}])
    result_chunk = ((), "messages", [result_msg, {}])

    reader = GraphStreamChunkReader(
        _dispatch_pause_result(dispatch_chunk, pause=2.0, result=result_chunk),
        idle_timeout=0.5,
        heartbeat_interval=0.2,
        step_id="TST-02",
    )

    chunk = await reader.read_next()
    assert chunk == dispatch_chunk

    heartbeat_count = 0
    while True:
        chunk = await reader.read_next()
        if chunk is _STREAM_HEARTBEAT_SENTINEL:
            heartbeat_count += 1
            continue
        assert chunk == result_chunk
        break

    assert heartbeat_count >= 1, "Expected at least one heartbeat during tool execution"

    with pytest.raises(StopAsyncIteration):
        await reader.read_next()


# --- Per-tool wall-clock cap (tool_timeout) ---


@pytest.mark.asyncio
async def test_tool_timeout_fires_when_tool_runs_too_long() -> None:
    """tool_timeout caps the root tool-wave wall-clock time."""
    dispatch_msg = AIMessage(
        content="",
        tool_calls=[{"name": "run_command", "args": {"command": "ls"}, "id": "c1"}],
    )
    dispatch_chunk = ((), "messages", [dispatch_msg, {}])

    reader = GraphStreamChunkReader(
        _dispatch_pause_result(
            dispatch_chunk,
            pause=10.0,
            result=((), "messages", [ToolMessage(content="late", tool_call_id="c1"), {}]),
        ),
        idle_timeout=0.0,
        tool_timeout=0.5,
        heartbeat_interval=0.2,
        step_id="TST-03",
    )

    chunk = await reader.read_next()
    assert chunk == dispatch_chunk

    with pytest.raises(DispatchTimeoutError) as exc_info:
        while True:
            await reader.read_next()

    assert exc_info.value.timeout_seconds == 0.5
    assert exc_info.value.step_id == "TST-03"
    assert exc_info.value.reason == "tool_wall_clock"
    assert "tool" in str(exc_info.value).lower()


# --- Legacy compatibility removed: use idle_timeout ---


@pytest.mark.asyncio
async def test_idle_timeout_via_explicit_field() -> None:
    """idle_timeout catches deadlocks when no root tool is pending."""
    reader = GraphStreamChunkReader(
        _slow_single_chunk(delay=10.0),
        idle_timeout=0.4,
        heartbeat_interval=0.2,
        step_id="TST-04",
    )

    with pytest.raises(DispatchTimeoutError):
        while True:
            chunk = await reader.read_next()
            if chunk is _STREAM_HEARTBEAT_SENTINEL:
                continue
            break  # pragma: no cover


# --- Timeouts disabled + sentinel cap ---


@pytest.mark.asyncio
async def test_no_timeouts_heartbeats_until_cancelled() -> None:
    """When idle/tool timeouts are 0, heartbeats continue until cancel."""
    reader = GraphStreamChunkReader(
        _slow_single_chunk(delay=10.0),
        idle_timeout=0,
        tool_timeout=0,
        heartbeat_interval=0.2,
        max_heartbeats=0,  # disable sentinel cap for this case
        step_id="TST-05",
    )

    for _ in range(3):
        chunk = await reader.read_next()
        assert chunk is _STREAM_HEARTBEAT_SENTINEL

    await reader.cancel()


@pytest.mark.asyncio
async def test_sentinel_cap_fires_when_idle() -> None:
    """Sentinel cap fires after max_heartbeats with no real chunks and no tools."""
    reader = GraphStreamChunkReader(
        _slow_single_chunk(delay=10.0),
        idle_timeout=0,
        tool_timeout=0,
        heartbeat_interval=0.1,
        max_heartbeats=3,
        step_id="TST-05b",
    )

    with pytest.raises(DispatchTimeoutError) as exc_info:
        while True:
            await reader.read_next()

    assert exc_info.value.reason == "sentinel_cap"


# --- Multiple tool cycles ---


async def _multi_tool_cycle() -> AsyncIterator[Any]:
    """Two complete tool cycles with pauses."""
    yield (
        (),
        "messages",
        [AIMessage(content="", tool_calls=[{"name": "t1", "args": {}, "id": "c1"}]), {}],
    )
    await asyncio.sleep(0.5)
    yield ((), "messages", [ToolMessage(content="r1", tool_call_id="c1"), {}])

    yield (
        (),
        "messages",
        [AIMessage(content="", tool_calls=[{"name": "t2", "args": {}, "id": "c2"}]), {}],
    )
    await asyncio.sleep(0.5)
    yield ((), "messages", [ToolMessage(content="r2", tool_call_id="c2"), {}])


@pytest.mark.asyncio
async def test_multiple_tool_cycles_no_false_positive() -> None:
    """Multiple dispatch→result cycles should not trigger idle timeout."""
    reader = GraphStreamChunkReader(
        _multi_tool_cycle(),
        idle_timeout=0.3,
        tool_timeout=5.0,
        heartbeat_interval=0.1,
        step_id="TST-06",
    )

    chunks_received: list[Any] = []
    while True:
        try:
            chunk = await reader.read_next()
        except StopAsyncIteration:
            break
        if chunk is _STREAM_HEARTBEAT_SENTINEL:
            continue
        chunks_received.append(chunk)

    assert len(chunks_received) == 4


# --- Parallel wave: first result must not clear remaining tools ---


@pytest.mark.asyncio
async def test_parallel_tools_first_result_does_not_enable_idle() -> None:
    """First of N ToolMessages must not make remaining tools look idle."""
    dispatch = (
        (),
        "messages",
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "fast", "args": {}, "id": "c1"},
                    {"name": "slow", "args": {}, "id": "c2"},
                ],
            ),
            {},
        ],
    )
    fast_result = ((), "messages", [ToolMessage(content="fast", tool_call_id="c1"), {}])
    slow_result = ((), "messages", [ToolMessage(content="slow", tool_call_id="c2"), {}])

    reader = GraphStreamChunkReader(
        _emit_sequence(
            [
                (0.0, dispatch),
                (0.2, fast_result),
                # Gap after first result would trip idle=0.4 if counter cleared early
                (1.0, slow_result),
            ]
        ),
        idle_timeout=0.4,
        tool_timeout=0,
        heartbeat_interval=0.15,
        step_id="TST-07",
    )

    chunks: list[Any] = []
    while True:
        try:
            chunk = await reader.read_next()
        except StopAsyncIteration:
            break
        if chunk is _STREAM_HEARTBEAT_SENTINEL:
            continue
        chunks.append(chunk)

    assert len(chunks) == 3


# --- Nested subgraph messages under active parent ---


@pytest.mark.asyncio
async def test_nested_tool_message_does_not_clear_parent_activity() -> None:
    """Nested ToolMessage is progress only; parent task stays pending."""
    parent_dispatch = (
        ("execute:run-1",),
        "messages",
        [AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "parent"}]), {}],
    )
    nested_result = (
        ("tools:subagent",),
        "messages",
        [ToolMessage(content="nested-done", tool_call_id="nested-1"), {}],
    )
    parent_result = (
        ("execute:run-1",),
        "messages",
        [ToolMessage(content="parent-done", tool_call_id="parent"), {}],
    )

    reader = GraphStreamChunkReader(
        _emit_sequence(
            [
                (0.0, parent_dispatch),
                (0.2, nested_result),
                # Long gap after nested result; idle must stay suppressed
                (1.0, parent_result),
            ]
        ),
        idle_timeout=0.4,
        tool_timeout=0,
        heartbeat_interval=0.15,
        step_id="TST-08",
    )

    chunks: list[Any] = []
    while True:
        try:
            chunk = await reader.read_next()
        except StopAsyncIteration:
            break
        if chunk is _STREAM_HEARTBEAT_SENTINEL:
            continue
        chunks.append(chunk)

    assert len(chunks) == 3


# --- Sentinel cap suspended while tools active ---


@pytest.mark.asyncio
async def test_sentinel_cap_suspended_while_tool_active() -> None:
    """Sentinel cap must not kill a long-running root tool."""
    dispatch = (
        (),
        "messages",
        [AIMessage(content="", tool_calls=[{"name": "slow", "args": {}, "id": "c1"}]), {}],
    )
    result = ((), "messages", [ToolMessage(content="done", tool_call_id="c1"), {}])

    reader = GraphStreamChunkReader(
        # Poll interval is 0.5s; use a multi-second tool gap so heartbeats exceed
        # max_heartbeats without raising while the tool is still pending.
        _dispatch_pause_result(dispatch, pause=2.5, result=result),
        idle_timeout=0,
        tool_timeout=0,
        heartbeat_interval=0.4,
        max_heartbeats=3,
        step_id="TST-09",
    )

    assert await reader.read_next() == dispatch

    heartbeats = 0
    while True:
        chunk = await reader.read_next()
        if chunk is _STREAM_HEARTBEAT_SENTINEL:
            heartbeats += 1
            continue
        assert chunk == result
        break

    assert heartbeats > 3, "Expected heartbeats beyond max_heartbeats without sentinel_cap"
