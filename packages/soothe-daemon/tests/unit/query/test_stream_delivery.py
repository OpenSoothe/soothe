"""Tests for daemon stream delivery coalescing."""

from __future__ import annotations

import time
from typing import Any

from soothe_sdk.core.events import STREAM_END

from soothe_daemon.query.stream_delivery import (
    STRANGE_LOOP_COMPLETED,
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


def _messages(
    tuples: list[tuple[tuple[str, ...], str, Any]],
) -> list[tuple[tuple[str, ...], str, Any]]:
    return [item for item in tuples if item[1] == "messages"]


def _custom(
    tuples: list[tuple[tuple[str, ...], str, Any]],
    *,
    event_type: str | None = None,
) -> list[tuple[tuple[str, ...], str, Any]]:
    items = [item for item in tuples if item[1] == "custom"]
    if event_type is None:
        return items
    return [item for item in items if item[2].get("type") == event_type]


def _stream_end_scopes(tuples: list[tuple[tuple[str, ...], str, Any]]) -> list[str]:
    return [str(item[2].get("scope")) for item in _custom(tuples, event_type=STREAM_END)]


def test_batch_mode_suppresses_goal_completion_until_completed() -> None:
    coalescer = StreamDeliveryCoalescer("batch")
    assert coalescer.ingest(*_gc_chunk("a")) == []
    assert coalescer.ingest(*_gc_chunk("b")) == []
    done = coalescer.ingest(
        (),
        "custom",
        {"type": STRANGE_LOOP_COMPLETED, "status": "done"},
    )
    assert len(_messages(done)) == 1
    coalesced_msg = done[0][2][0]
    assert coalesced_msg["content"] == "ab"
    assert coalesced_msg.get("chunk_position") == "last"
    assert len(_custom(done, event_type=STRANGE_LOOP_COMPLETED)) == 1
    assert _stream_end_scopes(done) == ["generation", "phase"]
    assert coalescer.turn_complete_pending


def test_consume_turn_complete_pending_returns_and_clears() -> None:
    """IG-556: QueryEngine uses consume_turn_complete_pending after stream end."""
    coalescer = StreamDeliveryCoalescer("batch")
    coalescer.ingest(*_gc_chunk("tail"))
    coalescer.ingest(
        (),
        "custom",
        {"type": STRANGE_LOOP_COMPLETED, "status": "done"},
    )
    assert coalescer.turn_complete_pending is True
    assert coalescer.consume_turn_complete_pending() is True
    assert coalescer.turn_complete_pending is False
    assert coalescer.consume_turn_complete_pending() is False
    assert coalescer.flush() == []


def test_adaptive_small_goal_completion_passthrough() -> None:
    coalescer = StreamDeliveryCoalescer("adaptive")
    chunk = _gc_chunk("passthrough")
    out = coalescer.ingest(*chunk)
    assert len(out) == 1
    assert out[0][1] == "messages"
    assert out[0][2][0]["content"] == "passthrough"
    assert out[0][2][0]["phase"] == "goal_completion"


def test_coalesce_interval_100_faster_first_emit_than_300_baseline() -> None:
    """IG-534 Phase 3: shorter coalesce interval reduces time-to-first-chunk."""

    def _time_to_first_emit_ms(interval_ms: int) -> float | None:
        coalescer = StreamDeliveryCoalescer(
            "adaptive",
            coalesce_interval_ms=interval_ms,
        )
        started = time.monotonic()
        assert coalescer.ingest(*_text_chunk("hello")) == []
        time.sleep(0.12)
        out = coalescer.ingest(*_text_chunk(" world"))
        if out:
            return (time.monotonic() - started) * 1000.0
        return None

    fast_ms = _time_to_first_emit_ms(100)
    slow_ms = _time_to_first_emit_ms(300)
    assert fast_ms is not None, "100ms coalesce should emit within 120ms idle"
    assert slow_ms is None, "300ms coalesce should not emit within 120ms idle"


def test_text_chunks_coalesce_until_last() -> None:
    coalescer = StreamDeliveryCoalescer("adaptive", coalesce_interval_ms=10_000)
    assert coalescer.ingest(*_text_chunk("a")) == []
    assert coalescer.ingest(*_text_chunk("b")) == []
    flushed = coalescer.ingest(*_text_chunk("c", last=True))
    assert len(_messages(flushed)) == 1
    msg = flushed[0][2][0]
    assert msg["content"] == "abc"
    assert msg.get("chunk_position") == "last"
    assert _stream_end_scopes(flushed) == ["generation"]
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
    out = coalescer.ingest((), "messages", wire)
    batches = [item for item in out if item[1] == "custom"]
    assert len(batches) == 1
    assert batches[0][2]["type"] == "tool_call_updates_batch"
    assert batches[0][2]["count"] == 1
    assert coalescer.flush() == []


def test_tool_batch_flushes_immediately_without_waiting_for_tool_result() -> None:
    """New tool invocations must reach the client before a long-running tool returns."""
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
    out = coalescer.ingest((), "messages", wire)
    assert any(
        item[1] == "custom" and item[2].get("type") == "tool_call_updates_batch" for item in out
    )
    # Simulate a long tool run with no further stream chunks until the result.
    assert coalescer.ingest(*_tool_chunk()) == [((), "messages", _tool_chunk()[2])]


def test_tool_batch_merges_later_displayable_args_for_same_id() -> None:
    """Buffered updates for the same tool_call_id must upgrade in place before flush."""
    coalescer = StreamDeliveryCoalescer("adaptive", tool_batch_interval_ms=10_000)
    ns = ("execute:abc", "tools:sub")
    now = time.monotonic()
    placeholder = {
        "type": "soothe.stream.tool_call.update",
        "tool_call_id": "LWZ_01:t0:read_file:0",
        "name": "read_file",
        "args": {"_subgraph_tool": True},
    }
    enriched = {
        "type": "soothe.stream.tool_call.update",
        "tool_call_id": "LWZ_01:t0:read_file:0",
        "name": "read_file",
        "args": {"path": "/docs/specs/RFC-450.md"},
    }
    assert coalescer._accumulate_tool_batch(ns, [placeholder], now) is True
    assert coalescer._accumulate_tool_batch(ns, [enriched], now) is True

    flushed = coalescer._flush_tool_batch(ns, force=True)
    assert flushed
    batch = flushed[0][2]
    assert batch["updates"][0]["args"] == {"path": "/docs/specs/RFC-450.md"}


def test_custom_tool_update_not_suppressed_when_batch_has_placeholder() -> None:
    coalescer = StreamDeliveryCoalescer("adaptive", tool_batch_interval_ms=10_000)
    ns = ("execute:abc", "tools:sub")
    placeholder_wire = (
        {
            "type": "ai",
            "content": "",
            "tool_calls": [
                {
                    "id": "LWZ_01:t0:glob:1",
                    "name": "glob",
                    "args": {},
                },
            ],
        },
        {},
    )
    coalescer.ingest(ns, "messages", placeholder_wire)

    enriched = {
        "type": "soothe.stream.tool_call.update",
        "tool_call_id": "LWZ_01:t0:glob:1",
        "name": "glob",
        "args": {"glob_pattern": "**/*.py"},
    }
    out = coalescer.ingest(ns, "custom", enriched)
    assert any(item[1] == "custom" and item[2] == enriched for item in out)


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
    """IG-436: Verify goal_completion flushed when STRANGE_LOOP_COMPLETED arrives."""
    coalescer = StreamDeliveryCoalescer("batch")
    # Accumulate goal_completion chunks
    assert coalescer.ingest(*_gc_chunk("part1")) == []
    assert coalescer.ingest(*_gc_chunk("part2")) == []
    # STRANGE_LOOP_COMPLETED triggers flush
    done = coalescer.ingest(
        (),
        "custom",
        {"type": STRANGE_LOOP_COMPLETED, "status": "done"},
    )
    # Should have flushed goal_completion + stream.end scopes + completed event
    assert len(_messages(done)) == 1
    assert done[0][2][0]["phase"] == "goal_completion"
    assert done[0][2][0]["content"] == "part1part2"
    assert len(_custom(done, event_type=STRANGE_LOOP_COMPLETED)) == 1
    assert _stream_end_scopes(done) == ["generation", "phase"]
    assert coalescer.turn_complete_pending


def test_adaptive_mode_switches_to_chunked_streaming_on_threshold() -> None:
    """IG-441: After threshold, adaptive enters chunked-streaming (not pure batch).

    Pre-IG-441 the second phase was pure batch — every post-threshold chunk
    was held until ``strange_loop.completed``. With block_chars=1024 (default)
    and a short stream, the new behavior with default block thresholds still
    holds chunks until the final flush, preserving the no-duplicate guarantee:
    streamed bytes are NEVER re-emitted as part of a block.
    """
    coalescer = StreamDeliveryCoalescer("adaptive", adaptive_threshold_chars=10)
    out1 = coalescer.ingest(*_gc_chunk("abc"))
    assert len(out1) == 1
    assert out1[0][2][0]["content"] == "abc"
    assert coalescer.goal_completion_phase == "streaming"

    # Crossing the threshold transitions the coalescer into chunked-streaming;
    # under defaults (block_chars=1024) this small chunk does not yet trigger a
    # size-based block flush, so the chunk is buffered.
    out2 = coalescer.ingest(*_gc_chunk("defghijklmn"))
    assert out2 == []
    assert coalescer.goal_completion_phase == "chunked_streaming"

    done = coalescer.ingest(
        (),
        "custom",
        {"type": STRANGE_LOOP_COMPLETED, "status": "done"},
    )
    assert len(_messages(done)) == 1
    # Final block carries only post-threshold content; streamed "abc" is never
    # re-emitted.
    assert done[0][2][0]["content"] == "defghijklmn"
    assert done[0][2][0]["chunk_position"] == "last"
    assert _stream_end_scopes(done) == ["generation", "phase"]


def test_adaptive_chunked_streaming_emits_size_based_blocks() -> None:
    """IG-441: In chunked-streaming phase, size-based block flush kicks in.

    With ``adaptive_threshold_chars=5`` and ``adaptive_block_chars=10``:
    - first chunk "abc" (3 chars) streams individually (phase=streaming).
    - second chunk "defghij" (7 chars) crosses threshold, transitions phase
      and accumulates (buffer=7, below block_chars=10 → no flush).
    - third chunk "kl" (2 chars) does not push buffer to 10 yet.
    - fourth chunk "mnopqr" (6 chars) → buffer=15 ≥ 10 → emit a block
      ("defghijklmnopqr") and reset.
    - strange_loop.completed flushes any remainder (none here) and emits the
      completed event.
    """
    coalescer = StreamDeliveryCoalescer(
        "adaptive",
        adaptive_threshold_chars=5,
        adaptive_block_chars=10,
        adaptive_block_interval_ms=2000,  # disable time-based flush for determinism
    )

    streamed = coalescer.ingest(*_gc_chunk("abc"))
    assert len(streamed) == 1
    assert coalescer.goal_completion_phase == "streaming"

    assert coalescer.ingest(*_gc_chunk("defghij")) == []
    assert coalescer.goal_completion_phase == "chunked_streaming"
    assert coalescer.ingest(*_gc_chunk("kl")) == []

    block_out = coalescer.ingest(*_gc_chunk("mnopqr"))
    assert len(block_out) == 1
    block_msg = block_out[0][2][0]
    assert block_msg["phase"] == "goal_completion"
    assert block_msg["content"] == "defghijklmnopqr"
    # Intermediate block must NOT carry chunk_position=last.
    assert "chunk_position" not in block_msg or block_msg.get("chunk_position") != "last"
    assert coalescer.goal_completion_block_flush_count == 1

    done = coalescer.ingest(
        (),
        "custom",
        {"type": STRANGE_LOOP_COMPLETED, "status": "done"},
    )
    # Buffer was empty after the block flush; terminal re-stamps last content block.
    assert len(_messages(done)) == 1
    marker = done[0][2][0]
    assert marker["phase"] == "goal_completion"
    assert marker["content"] == "defghijklmnopqr"
    assert marker["chunk_position"] == "last"
    assert marker.get("stream_terminal") is True
    assert len(_custom(done, event_type=STRANGE_LOOP_COMPLETED)) == 1
    assert _stream_end_scopes(done) == ["generation", "phase"]


def test_adaptive_chunked_streaming_time_based_block_flush() -> None:
    """IG-441: Time-based block flush triggers when block_interval elapses.

    Even when buffered chars are below ``adaptive_block_chars``, the coalescer
    must emit a block once ``adaptive_block_interval_ms`` has elapsed so slow
    streams still show progress. Drives time via a controlled monotonic clock.
    """
    import soothe_daemon.query.stream_delivery as sd

    fake_clock = [1000.0]

    def _fake_monotonic() -> float:
        return fake_clock[0]

    real_monotonic = sd.time.monotonic
    sd.time.monotonic = _fake_monotonic  # type: ignore[assignment]
    try:
        coalescer = StreamDeliveryCoalescer(
            "adaptive",
            adaptive_threshold_chars=3,
            adaptive_block_chars=10_000,  # disable size-based flush
            adaptive_block_interval_ms=200,
        )

        # Cross the threshold so we land in chunked_streaming.
        coalescer.ingest(*_gc_chunk("abcd"))
        assert coalescer.goal_completion_phase == "chunked_streaming"

        # Inject more buffered content; size threshold is far away.
        fake_clock[0] += 0.05  # 50ms
        out_under = coalescer.ingest(*_gc_chunk("xy"))
        assert out_under == []
        assert coalescer.goal_completion_block_flush_count == 0

        # Advance past block_interval; next ingest should flush prior buffer
        # via the time-based block flush on the new chunk.
        fake_clock[0] += 0.25  # 250ms past last_block
        out_after = coalescer.ingest(*_gc_chunk("z"))
        assert len(out_after) == 1
        block_msg = out_after[0][2][0]
        assert block_msg["phase"] == "goal_completion"
        # Time-based flush ran at start of ingest BEFORE the new chunk was
        # accumulated, so only prior buffer ("abcdxy") is in this block.
        assert block_msg["content"] == "abcdxy"
        assert coalescer.goal_completion_block_flush_count == 1

        # The "z" chunk is now buffered; final flush at completed event.
        done = coalescer.ingest(
            (),
            "custom",
            {"type": STRANGE_LOOP_COMPLETED, "status": "done"},
        )
        assert len(_messages(done)) == 1
        assert done[0][2][0]["content"] == "z"
        assert done[0][2][0]["chunk_position"] == "last"
        assert _stream_end_scopes(done) == ["generation", "phase"]
    finally:
        sd.time.monotonic = real_monotonic  # type: ignore[assignment]


def test_streaming_mode_passthrough_every_goal_completion_chunk() -> None:
    """IG-441: ``streaming`` mode forwards every goal_completion chunk verbatim.

    No buffering, no threshold, no chunked-streaming transition. The phase
    tracker stays in ``streaming`` for the lifetime of the turn — this is the
    native LLM generation rate.
    """
    coalescer = StreamDeliveryCoalescer(
        "streaming",
        # Generous thresholds to prove they don't apply in streaming mode.
        adaptive_threshold_chars=3,
        adaptive_block_chars=4,
        adaptive_block_interval_ms=10_000,
    )

    out1 = coalescer.ingest(*_gc_chunk("hello "))
    out2 = coalescer.ingest(*_gc_chunk("world "))
    out3 = coalescer.ingest(*_gc_chunk("streaming!"))
    assert len(out1) == 1 and out1[0][2][0]["content"] == "hello "
    assert len(out2) == 1 and out2[0][2][0]["content"] == "world "
    assert len(out3) == 1 and out3[0][2][0]["content"] == "streaming!"
    # No buffering and no intermediate block emissions.
    assert coalescer.goal_completion_phase == "streaming"
    assert coalescer.goal_completion_block_flush_count == 0

    # ``strange_loop.completed`` only emits the custom event — nothing was buffered.
    done = coalescer.ingest(
        (),
        "custom",
        {"type": STRANGE_LOOP_COMPLETED, "status": "done"},
    )
    assert len(done) == 1
    assert done[0][2]["type"] == STRANGE_LOOP_COMPLETED


def test_streaming_mode_file_output_still_buffers() -> None:
    """IG-441: file_output_threshold overrides ``streaming`` mode to pure batch.

    file_output cannot stream — it needs the full text in one place to decide
    between file vs. wire delivery. ``streaming`` mode + file_output therefore
    falls back to the buffer-everything path.
    """
    coalescer = StreamDeliveryCoalescer(
        "streaming",
        file_output_threshold_chars=10_000,  # very high → file path never taken
    )
    assert coalescer.ingest(*_gc_chunk("alpha")) == []
    assert coalescer.ingest(*_gc_chunk("bravo")) == []
    done = coalescer.ingest(
        (),
        "custom",
        {"type": STRANGE_LOOP_COMPLETED, "status": "done"},
    )
    assert len(_messages(done)) == 1
    assert done[0][2][0]["content"] == "alphabravo"
    assert done[0][2][0]["chunk_position"] == "last"
    assert _stream_end_scopes(done) == ["generation", "phase"]


def test_adaptive_chunked_streaming_with_file_output_uses_pure_batch() -> None:
    """IG-441: When file_output_threshold_chars > 0, adaptive falls back to pure batch.

    file_output needs the entire goal_completion text in one place to decide
    whether to write the file. Streaming intermediate blocks would defeat
    that, so the coalescer reverts to buffer-everything behavior.
    """
    coalescer = StreamDeliveryCoalescer(
        "adaptive",
        adaptive_threshold_chars=3,
        adaptive_block_chars=4,
        file_output_threshold_chars=50_000,  # never actually triggers file
    )
    assert coalescer.ingest(*_gc_chunk("abcd")) == []
    assert coalescer.ingest(*_gc_chunk("efgh")) == []
    assert coalescer.goal_completion_block_flush_count == 0
    done = coalescer.ingest(
        (),
        "custom",
        {"type": STRANGE_LOOP_COMPLETED, "status": "done"},
    )
    assert len(_messages(done)) == 1
    assert done[0][2][0]["content"] == "abcdefgh"
    assert _stream_end_scopes(done) == ["generation", "phase"]


def test_streaming_mode_emits_stream_end_after_terminal() -> None:
    """IG-556 P2: terminal content is followed by soothe.stream.end scopes."""
    from soothe_sdk.core.events import STREAM_END

    coalescer = StreamDeliveryCoalescer("streaming")
    out = coalescer.ingest(*_gc_chunk("final", last=True))
    custom = [item for item in out if item[1] == "custom"]
    assert any(
        item[2].get("type") == STREAM_END and item[2].get("scope") == "generation"
        for item in custom
    )
    assert any(
        item[2].get("type") == STREAM_END and item[2].get("scope") == "phase" for item in custom
    )


def test_streaming_mode_stamps_stream_terminal_on_last_chunk() -> None:
    """IG-556 P1.2: streaming passthrough stamps stream_terminal on final chunk."""
    coalescer = StreamDeliveryCoalescer("streaming")
    out = coalescer.ingest(*_gc_chunk("final", last=True))
    assert len(_messages(out)) == 1
    msg = out[0][2][0]
    assert msg.get("stream_terminal") is True
    assert msg.get("chunk_position") == "last"
    assert _stream_end_scopes(out) == ["generation", "phase"]


def test_chunk_position_last_flushes_goal_completion_without_completed_event() -> None:
    """IG-556 P1.1: chunk_position=last forces immediate namespace flush."""
    coalescer = StreamDeliveryCoalescer("batch")
    assert coalescer.ingest(*_gc_chunk("a")) == []
    out = coalescer.ingest(*_gc_chunk("b", last=True))
    msgs = [item for item in out if item[1] == "messages"]
    assert len(msgs) == 1
    body = msgs[0][2][0]
    assert body["content"] == "ab"
    assert body.get("stream_terminal") is True
    assert body.get("chunk_position") == "last"
