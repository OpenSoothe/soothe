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


def _text_chunk(content: str, *, last: bool = False) -> tuple[tuple[()], str, tuple]:
    msg: dict = {"type": "AIMessageChunk", "content": content}
    if last:
        msg["chunk_position"] = "last"
    return ((), "messages", (msg, {}))


def _tool_chunk() -> tuple[tuple[()], str, tuple]:
    return (
        (),
        "messages",
        ({"type": "tool", "content": "ok", "tool_call_id": "tc-1"}, {}),
    )


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
    coalesced_msg = done[0][2][0]
    assert coalesced_msg["content"] == "ab"
    assert coalesced_msg.get("chunk_position") == "last"
    assert done[1][2]["type"] == AGENT_LOOP_COMPLETED
    assert coalescer.turn_complete_pending


def test_adaptive_small_goal_completion_passthrough() -> None:
    coalescer = StreamDeliveryCoalescer("adaptive")
    chunk = _gc_chunk("passthrough")
    out = coalescer.ingest(*chunk)
    assert len(out) == 1
    assert out[0][1] == "messages"
    assert out[0][2][0]["content"] == "passthrough"
    assert out[0][2][0]["phase"] == "goal_completion"


def test_text_chunks_coalesce_until_last() -> None:
    coalescer = StreamDeliveryCoalescer("adaptive", coalesce_interval_ms=10_000)
    assert coalescer.ingest(*_text_chunk("a")) == []
    assert coalescer.ingest(*_text_chunk("b")) == []
    flushed = coalescer.ingest(*_text_chunk("c", last=True))
    assert len(flushed) == 1
    msg = flushed[0][2][0]
    assert msg["content"] == "abc"
    assert msg.get("chunk_position") == "last"
    assert coalescer.coalesce_flush_count == 1


def test_tool_message_flushes_pending_text_first() -> None:
    coalescer = StreamDeliveryCoalescer("adaptive", coalesce_interval_ms=10_000)
    assert coalescer.ingest(*_text_chunk("pending")) == []
    out = coalescer.ingest(*_tool_chunk())
    assert len(out) == 2
    assert out[0][2][0]["content"] == "pending"
    assert out[1][1] == "messages"
    assert out[1][2][0]["type"] == "tool"


def test_updates_mode_dropped_unless_interrupt() -> None:
    coalescer = StreamDeliveryCoalescer("adaptive")
    assert coalescer.ingest((), "updates", {"model": {"messages": []}}) == []
    kept = coalescer.ingest((), "updates", {"__interrupt__": []})
    assert kept == [((), "updates", {"__interrupt__": []})]


def test_custom_event_flushes_text_buffer() -> None:
    coalescer = StreamDeliveryCoalescer("adaptive", coalesce_interval_ms=10_000)
    assert coalescer.ingest(*_text_chunk("buf")) == []
    out = coalescer.ingest(
        (), "custom", {"type": "soothe.stream.tool_call.update", "tool_call_id": "x"}
    )
    assert len(out) == 2
    assert out[0][2][0]["content"] == "buf"


def test_internal_custom_event_dropped_at_ingest() -> None:
    coalescer = StreamDeliveryCoalescer("adaptive")
    out = coalescer.ingest(
        (),
        "custom",
        {"type": "soothe.internal.policy.checked", "verdict": "allow"},
    )
    assert out == []


def test_tool_invocation_batches_and_strips_ai() -> None:
    coalescer = StreamDeliveryCoalescer("adaptive", tool_batch_interval_ms=10_000)
    wire = (
        {
            "type": "ai",
            "content": "",
            "tool_calls": [
                {"id": "tc-1", "name": "read_file", "args": {"path": "/x"}},
            ],
        },
        {},
    )
    assert coalescer.ingest((), "messages", wire) == []
    flushed = coalescer.flush()
    batches = [item for item in flushed if item[1] == "custom"]
    assert len(batches) == 1
    assert batches[0][2]["type"] == "tool_call_updates_batch"
    assert batches[0][2]["count"] == 1


def test_strip_tool_metadata_for_batch() -> None:
    coalescer = StreamDeliveryCoalescer("adaptive")
    wire = (
        {
            "type": "ai",
            "content": "",
            "tool_calls": [{"id": "tc-1", "name": "read_file", "args": {"path": "/x"}}],
        },
        {},
    )
    stripped = coalescer.strip_tool_metadata_for_batch(wire)
    body = stripped[0]
    assert "tool_calls" not in body
    assert "tool_call_chunks" not in body


def test_batch_mode_flushes_goal_completion_on_completed_event() -> None:
    """IG-436: Verify goal_completion flushed when AGENT_LOOP_COMPLETED arrives."""
    coalescer = StreamDeliveryCoalescer("batch")
    # Accumulate goal_completion chunks
    assert coalescer.ingest(*_gc_chunk("part1")) == []
    assert coalescer.ingest(*_gc_chunk("part2")) == []
    # AGENT_LOOP_COMPLETED triggers flush
    done = coalescer.ingest(
        (),
        "custom",
        {"type": AGENT_LOOP_COMPLETED, "status": "done"},
    )
    # Should have flushed goal_completion + completed event
    assert len(done) == 2
    assert done[0][1] == "messages"
    assert done[0][2][0]["phase"] == "goal_completion"
    assert done[0][2][0]["content"] == "part1part2"
    assert done[1][2]["type"] == AGENT_LOOP_COMPLETED
    assert coalescer.turn_complete_pending


def test_adaptive_mode_switches_to_batch_on_threshold() -> None:
    """IG-436: Adaptive mode batches when exceeding threshold chars."""
    coalescer = StreamDeliveryCoalescer("adaptive", adaptive_threshold_chars=10)
    # First chunk under threshold - passthrough
    out1 = coalescer.ingest(*_gc_chunk("abc"))
    assert len(out1) == 1
    assert out1[0][2][0]["content"] == "abc"
    # Second chunk exceeds threshold - switches to batch mode
    out2 = coalescer.ingest(*_gc_chunk("defghijklmn"))  # 11 chars
    assert len(out2) == 0  # Buffered, not passed through
    # Flush on completed
    done = coalescer.ingest(
        (),
        "custom",
        {"type": AGENT_LOOP_COMPLETED, "status": "done"},
    )
    assert len(done) == 2
    # Coalesced content includes both chunks
    assert done[0][2][0]["content"] == "abcdefghijklmn"
