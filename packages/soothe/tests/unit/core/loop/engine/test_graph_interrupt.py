"""Tests for LangGraph interrupt auto-resume helpers (RFC-622)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from soothe.sloop.engine.graph_interrupt import (
    _STREAM_HEARTBEAT_SENTINEL,
    DispatchTimeoutError,
    GraphStreamChunkReader,
    build_auto_resume_payload,
    is_ask_user_interrupt,
)


async def _chunks_with_slow_second(
    first: str = "first", second: str = "second"
) -> AsyncIterator[str]:
    yield first
    await asyncio.sleep(1.0)
    yield second


@pytest.mark.asyncio
async def test_graph_stream_chunk_reader_survives_heartbeat() -> None:
    """IG-549: heartbeat sentinels must not close the underlying async iterator."""
    reader = GraphStreamChunkReader(
        _chunks_with_slow_second(),
        heartbeat_interval=0.3,
    )

    assert await reader.read_next() == "first"

    heartbeat = await reader.read_next()
    assert heartbeat is _STREAM_HEARTBEAT_SENTINEL

    assert await reader.read_next() == "second"

    with pytest.raises(StopAsyncIteration):
        await reader.read_next()


async def _slow_single_chunk(value: str = "only", delay: float = 5.0) -> AsyncIterator[str]:
    await asyncio.sleep(delay)
    yield value


@pytest.mark.asyncio
async def test_graph_stream_chunk_reader_cancel_closes_pending_read() -> None:
    reader = GraphStreamChunkReader(
        _slow_single_chunk(),
        heartbeat_interval=0.3,
    )
    heartbeat = await reader.read_next()
    assert heartbeat is _STREAM_HEARTBEAT_SENTINEL
    await reader.cancel()

    with pytest.raises(StopAsyncIteration):
        await reader.read_next()


@pytest.mark.asyncio
async def test_graph_stream_chunk_reader_dispatch_timeout_raises() -> None:
    """Dispatch watchdog raises when no chunk arrives within the deadline."""
    reader = GraphStreamChunkReader(
        _slow_single_chunk(delay=10.0),
        dispatch_timeout=0.4,
        heartbeat_interval=0.2,
        step_id="KFD-05",
    )

    with pytest.raises(DispatchTimeoutError) as exc_info:
        while True:
            chunk = await reader.read_next()
            if chunk is _STREAM_HEARTBEAT_SENTINEL:
                continue
            break  # pragma: no cover

    assert exc_info.value.timeout_seconds == 0.4
    assert exc_info.value.step_id == "KFD-05"


def test_auto_resume_tool_interrupt_payload() -> None:
    pending = {
        "i1": {
            "action_requests": [{"name": "write_file", "args": {"path": "a.txt"}}],
        }
    }
    out = build_auto_resume_payload(pending)
    assert out == {"i1": {"decisions": [{"type": "approve"}]}}


def test_auto_resume_skips_ask_user_payload() -> None:
    """RFC-622: ``ask_user`` no longer auto-resumed; routed via ClarificationPolicy."""
    pending = {"i2": {"type": "ask_user", "questions": ["q1", "q2"]}}
    out = build_auto_resume_payload(pending)
    assert out == {}


def test_auto_resume_mixed_payload_keeps_action_approvals() -> None:
    pending = {
        "i1": {"action_requests": [{"name": "x"}]},
        "i2": {"type": "ask_user", "questions": ["q"]},
    }
    out = build_auto_resume_payload(pending)
    assert out == {"i1": {"decisions": [{"type": "approve"}]}}


def test_is_ask_user_interrupt_matches() -> None:
    assert is_ask_user_interrupt({"type": "ask_user", "questions": ["q"]})


def test_is_ask_user_interrupt_rejects_non_mapping_and_other_types() -> None:
    assert not is_ask_user_interrupt(None)
    assert not is_ask_user_interrupt("ask_user")
    assert not is_ask_user_interrupt({"type": "review"})
    assert not is_ask_user_interrupt({})
