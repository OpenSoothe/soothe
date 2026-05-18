"""Tests for daemon stream delivery coalescing."""

from __future__ import annotations

from soothe_daemon.query.stream_delivery import (
    AGENT_LOOP_COMPLETED,
    StreamDeliveryCoalescer,
)


def _gc_chunk(content: str, *, last: bool = False) -> tuple[tuple[()], str, tuple]:
    msg: dict = {
        "type": "AIMessageChunk",
        "content": content,
        "phase": "goal_completion",
        "thread_id": "tid",
    }
    if last:
        msg["chunk_position"] = "last"
    return ((), "messages", (msg, {}))


def test_batch_mode_suppresses_goal_completion_until_completed() -> None:
    coalescer = StreamDeliveryCoalescer("batch")
    assert coalescer.ingest(*_gc_chunk("a")) == []
    assert coalescer.ingest(*_gc_chunk("b")) == []
    done = coalescer.ingest(
        (),
        "custom",
        {"type": AGENT_LOOP_COMPLETED, "status": "done"},
    )
    assert len(done) == 2
    assert done[0][1] == "messages"
    merged = done[0][2][0]
    assert merged["content"] == "ab"
    assert merged.get("chunk_position") == "last"
    assert done[1][2]["type"] == AGENT_LOOP_COMPLETED
    assert coalescer.turn_complete_pending


def test_merged_mode_flushes_on_threshold() -> None:
    coalescer = StreamDeliveryCoalescer("merged")
    small = "x" * 100
    assert coalescer.ingest(*_gc_chunk(small)) == []
    big = "y" * 500
    flushed = coalescer.ingest(*_gc_chunk(big))
    assert len(flushed) == 1
    assert "x" * 100 in flushed[0][2][0]["content"]
    assert "y" * 500 in flushed[0][2][0]["content"]


def test_full_mode_passthrough() -> None:
    coalescer = StreamDeliveryCoalescer("full")
    chunk = _gc_chunk("passthrough")
    assert coalescer.ingest(*chunk) == [chunk]
