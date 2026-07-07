"""IG-535 Optimization 1: Unit tests for priority-aware inbound queue drop policy."""

from __future__ import annotations

import pytest

from soothe_sdk.client.websocket import (
    _DROP_PRIORITY_CRITICAL,
    _DROP_PRIORITY_HIGH,
    _DROP_PRIORITY_NORMAL,
    WebSocketClient,
    _inbound_frame_drop_priority,
)


class TestInboundFrameDropPriority:
    """Tests for _inbound_frame_drop_priority helper function."""

    def test_none_sentinel_is_critical(self) -> None:
        """None sentinel (EOF marker) must never be dropped."""
        assert _inbound_frame_drop_priority(None) == _DROP_PRIORITY_CRITICAL

    def test_status_idle_is_critical(self) -> None:
        """Terminal status:idle frame must never be dropped."""
        event = {"type": "status", "state": "idle", "loop_id": "test-123"}
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_status_running_is_critical(self) -> None:
        """status:running frame must never be dropped."""
        event = {"type": "status", "state": "running", "loop_id": "test-123"}
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_status_stopped_is_critical(self) -> None:
        """status:stopped frame must never be dropped."""
        event = {"type": "status", "state": "stopped", "loop_id": "test-123"}
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_error_frame_is_critical(self) -> None:
        """Error frames must never be dropped."""
        event = {
            "type": "error",
            "error": {"code": -32603, "message": "Internal error"},
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_connection_ack_is_critical(self) -> None:
        """connection_ack must never be dropped."""
        event = {
            "type": "connection_ack",
            "result": {"readiness_state": "ready"},
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_goal_completion_messages_is_critical(self) -> None:
        """goal_completion phase in messages mode must never be dropped."""
        event = {
            "type": "event",
            "mode": "messages",
            "data": ({"phase": "goal_completion", "content": "Final answer"}, {}),
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_goal_completion_in_next_envelope_is_critical(self) -> None:
        """goal_completion wrapped in protocol-1 next envelope must never be dropped."""
        event = {
            "type": "next",
            "payload": {
                "type": "event",
                "mode": "messages",
                "data": ({"phase": "goal_completion", "content": "Final"}, {}),
            },
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_cognition_event_is_high(self) -> None:
        """soothe.cognition.* events should be preferentially kept."""
        event = {
            "type": "event",
            "mode": "custom",
            "data": {
                "type": "soothe.cognition.step.started",
                "step_id": "step-1",
            },
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_HIGH

    def test_tool_call_updates_batch_is_high(self) -> None:
        """Tool call updates batch should be preferentially kept."""
        event = {
            "type": "event",
            "mode": "custom",
            "data": {
                "type": "soothe.ux.stream_tool_wire.tool_call_updates_batch",
                "updates": [{"tool_call_id": "t1"}],
            },
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_HIGH

    def test_event_batch_top_level_is_high(self) -> None:
        """Transport-level event_batch bundles user-visible frames — prefer keep."""
        event = {
            "type": "event_batch",
            "loop_id": "loop-1",
            "events": [
                {
                    "type": "event",
                    "mode": "custom",
                    "data": {"type": "soothe.cognition.step.started"},
                }
            ],
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_HIGH

    def test_tool_call_updates_batch_top_level_is_high(self) -> None:
        event = {"type": "tool_call_updates_batch", "updates": []}
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_HIGH

    def test_streaming_text_is_normal(self) -> None:
        """Regular streaming text chunks are acceptable drop candidates."""
        event = {
            "type": "event",
            "mode": "messages",
            "data": ({"content": "Some streaming text"}, {}),
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_NORMAL

    def test_updates_mode_is_normal(self) -> None:
        """Updates mode events are acceptable drop candidates."""
        event = {
            "type": "event",
            "mode": "updates",
            "data": {"todos": []},
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_NORMAL

    def test_error_custom_event_is_critical(self) -> None:
        """soothe.error.* custom events must never be dropped."""
        event = {
            "type": "event",
            "mode": "custom",
            "data": {
                "type": "soothe.error.runtime",
                "message": "Worker crashed",
            },
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_stream_degraded_is_critical(self) -> None:
        """stream_degraded signal must never be dropped."""
        event = {
            "type": "event",
            "mode": "custom",
            "data": {
                "type": "stream_degraded",
                "reason": "inbound_queue_overflow",
                "dropped_count": 42,
            },
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_stream_terminal_messages_is_critical(self) -> None:
        event = {
            "type": "event",
            "mode": "messages",
            "data": (
                {
                    "type": "AIMessageChunk",
                    "content": "done",
                    "stream_terminal": True,
                    "chunk_position": "last",
                },
                {},
            ),
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_chunk_position_last_plain_text_is_critical(self) -> None:
        event = {
            "type": "event",
            "mode": "messages",
            "data": ({"type": "AIMessageChunk", "content": "done", "chunk_position": "last"}, {}),
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_strange_loop_completed_is_critical(self) -> None:
        event = {
            "type": "event",
            "mode": "custom",
            "data": {"type": "soothe.cognition.strange_loop.completed", "status": "done"},
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_stream_end_event_is_critical(self) -> None:
        event = {
            "type": "event",
            "mode": "custom",
            "data": {"type": "soothe.stream.end", "scope": "turn"},
        }
        assert _inbound_frame_drop_priority(event) == _DROP_PRIORITY_CRITICAL

    def test_complete_envelope_is_critical(self) -> None:
        assert _inbound_frame_drop_priority({"type": "complete"}) == _DROP_PRIORITY_CRITICAL


@pytest.mark.asyncio
class TestPriorityAwareInboundQueue:
    """Tests for WebSocketClient._put_inbound_queue with priority-aware drop."""

    async def test_goal_completion_not_dropped_when_queue_full(self) -> None:
        """When queue is full, goal_completion should not be dropped."""
        client = WebSocketClient(url="ws://localhost:8765")
        # Simulate full queue with NORMAL priority items
        for i in range(client._inbound_maxsize):
            await client._inbound_queue.put(
                {"type": "event", "mode": "messages", "data": ({"content": f"text-{i}"}, {})}
            )
        assert client._inbound_queue.full()

        # Now try to put a critical goal_completion frame
        gc_event = {
            "type": "event",
            "mode": "messages",
            "data": ({"phase": "goal_completion", "content": "Final"}, {}),
        }
        await client._put_inbound_queue(gc_event)

        # Goal_completion should be in the queue (a NORMAL frame was dropped instead)
        found_gc = False
        while not client._inbound_queue.empty():
            item = await client._inbound_queue.get()
            if item and item.get("mode") == "messages":
                data = item.get("data")
                if isinstance(data, tuple) and data:
                    first = data[0]
                    if isinstance(first, dict) and first.get("phase") == "goal_completion":
                        found_gc = True
                        break

        assert found_gc, "goal_completion frame should have been admitted to queue"
        assert client._inbound_dropped > 0, "Some NORMAL frame should have been dropped"

    async def test_status_idle_not_dropped_when_queue_full(self) -> None:
        """When queue is full, status:idle should not be dropped."""
        client = WebSocketClient(url="ws://localhost:8765")
        # Fill queue with NORMAL priority items
        for i in range(client._inbound_maxsize):
            await client._inbound_queue.put(
                {"type": "event", "mode": "updates", "data": {"tick": i}}
            )
        assert client._inbound_queue.full()

        # Try to put critical status:idle frame
        status_event = {"type": "status", "state": "idle", "loop_id": "test"}
        await client._put_inbound_queue(status_event)

        # status:idle should be in queue
        found_status = False
        while not client._inbound_queue.empty():
            item = await client._inbound_queue.get()
            if item and item.get("type") == "status" and item.get("state") == "idle":
                found_status = True
                break

        assert found_status, "status:idle frame should have been admitted to queue"
        assert client._inbound_dropped > 0, "Some NORMAL frame should have been dropped"

    async def test_normal_frames_are_dropped_first(self) -> None:
        """When queue is full of mixed priorities, NORMAL frames are dropped first."""
        client = WebSocketClient(url="ws://localhost:8765")
        # Queue: mix of HIGH and NORMAL, ending with NORMAL at position N
        for i in range(client._inbound_maxsize - 10):
            await client._inbound_queue.put(
                {
                    "type": "event",
                    "mode": "custom",
                    "data": {"type": "soothe.cognition.step.started"},
                }
            )
        for i in range(10):
            await client._inbound_queue.put(
                {"type": "event", "mode": "messages", "data": ({"content": f"text-{i}"}, {})}
            )
        assert client._inbound_queue.full()

        # Try to put a new HIGH priority frame
        high_event = {
            "type": "event",
            "mode": "custom",
            "data": {"type": "soothe.cognition.step.completed"},
        }
        await client._put_inbound_queue(high_event)

        # Count HIGH frames - should have increased
        high_count = 0
        while not client._inbound_queue.empty():
            item = await client._inbound_queue.get()
            if _inbound_frame_drop_priority(item) == _DROP_PRIORITY_HIGH:
                high_count += 1

        # Original HIGH frames + new one should all be present
        assert high_count >= client._inbound_maxsize - 10 + 1
        assert client._inbound_dropped > 0, "Some NORMAL frame should have been dropped"

    async def test_terminal_frame_bumps_delivery_recv_seq(self) -> None:
        """IG-556 P1.3: terminal frames increment per-loop delivery recv sequence."""
        client = WebSocketClient(url="ws://localhost:8765")
        loop_id = "loop-terminal-ack"
        terminal = {
            "type": "event",
            "loop_id": loop_id,
            "mode": "messages",
            "data": (
                {
                    "type": "AIMessageChunk",
                    "content": "done",
                    "chunk_position": "last",
                    "stream_terminal": True,
                },
                {},
            ),
        }
        await client._put_inbound_queue(terminal)
        assert client._delivery_recv_seq.get(loop_id) == 1
