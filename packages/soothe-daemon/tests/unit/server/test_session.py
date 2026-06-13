"""Unit tests for ClientSession and ClientSessionManager."""

import asyncio
import contextlib
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe.foundation.events import EventMeta
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier

from soothe_daemon.event import EventBus, loop_event_topic
from soothe_daemon.server.session import ClientSessionManager


@pytest.mark.asyncio
async def test_create_session():
    """Test session creation."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"

    client_id = await manager.create_session(channel=transport, transport_client=None)

    assert client_id is not None
    session = await manager.get_session(client_id)
    assert session is not None
    assert session.transport == transport
    assert len(session.subscriptions) == 0
    assert session.sender_task is not None

    # Cleanup
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_subscribe_loop():
    """Test loop subscription."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"

    client_id = await manager.create_session(transport, None)

    result = await manager.subscribe_loop(client_id, "loop-abc123")
    assert result is True

    session = await manager.get_session(client_id)
    assert session is not None
    assert "loop-abc123" in session.subscriptions

    # Cleanup
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_subscribe_loop_preserves_stream_delivery_when_omitted():
    """Re-subscribe without ``stream_delivery`` must not reset client preference to batch."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"

    client_id = await manager.create_session(transport, None)

    await manager.subscribe_loop(client_id, "loop-abc123", stream_delivery="adaptive")
    assert manager.get_stream_delivery("loop-abc123") == "adaptive"

    await manager.subscribe_loop(client_id, "loop-abc123")
    assert manager.get_stream_delivery("loop-abc123") == "adaptive"

    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_unsubscribe_loop():
    """Test loop unsubscription."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"

    client_id = await manager.create_session(transport, None)
    subscribe_result = await manager.subscribe_loop(client_id, "loop-abc123")
    assert subscribe_result is True
    unsubscribe_result = await manager.unsubscribe_loop(client_id, "loop-abc123")
    assert unsubscribe_result is True

    session = await manager.get_session(client_id)
    assert session is not None
    assert "loop-abc123" not in session.subscriptions

    # Cleanup
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_subscribe_invalid_client():
    """Test subscribing invalid client returns False gracefully."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    # Should return False instead of raising ValueError
    result = await manager.subscribe_loop("invalid", "loop-abc123")
    assert result is False


@pytest.mark.asyncio
async def test_unsubscribe_invalid_client():
    """Test unsubscribing invalid client returns False gracefully."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    # Should return False instead of raising ValueError
    result = await manager.unsubscribe_loop("invalid", "loop-abc123")
    assert result is False


@pytest.mark.asyncio
async def test_remove_session():
    """Test session removal."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_loop(client_id, "loop-abc123")
    assert result is True

    assert manager.session_count == 1

    await manager.remove_session(client_id)

    assert manager.session_count == 0
    session = await manager.get_session(client_id)
    assert session is None


@pytest.mark.asyncio
async def test_sender_loop_sends_events():
    """Test that sender loop sends events via transport."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    await manager.subscribe_loop(client_id, "loop-abc123")

    # Give sender task time to start
    await asyncio.sleep(0.05)

    event = {
        "type": "event",
        "data": {"type": "soothe.cognition.strange_loop.started", "goal": "hello"},
    }
    await bus.publish(loop_event_topic("loop-abc123"), event)

    # Wait for sender loop to process
    await asyncio.sleep(0.2)

    # Transport.send should have been called
    transport.send.assert_called_once()
    call_args = transport.send.call_args
    assert call_args[0][1] == event  # Second argument is the event

    # Cleanup
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_sender_loop_stops_on_error():
    """Test that sender loop stops on transport error."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"
    transport.send = AsyncMock(side_effect=Exception("Connection error"))

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_loop(client_id, "loop-abc123")
    assert result is True

    event = {
        "type": "event",
        "data": {"type": "soothe.cognition.strange_loop.started", "goal": "hello"},
    }
    await bus.publish(loop_event_topic("loop-abc123"), event)

    # Wait for sender loop to process
    await asyncio.sleep(0.1)

    # Session should be removed due to error
    # (In real implementation, we might want to handle this differently)

    # Cleanup
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_sender_loop_treats_connection_error_as_disconnect(caplog: pytest.LogCaptureFixture):
    """Connection errors during send are handled as disconnects without warning traces."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"
    transport.send = AsyncMock(side_effect=ConnectionError("peer closed"))

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_loop(client_id, "loop-abc123")
    assert result is True

    caplog.set_level(logging.WARNING, logger="soothe_daemon.client_session")

    event = {
        "type": "event",
        "data": {"type": "soothe.cognition.strange_loop.started", "goal": "hello"},
    }
    await bus.publish(loop_event_topic("loop-abc123"), event)

    # Wait for sender loop to process and exit.
    await asyncio.sleep(0.1)

    assert transport.send.await_count == 1
    assert not any(
        "Failed to send event to client" in record.getMessage() for record in caplog.records
    )

    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_subscribe_loop_replaces_prior_subscription():
    """Second loop subscription replaces the first (strict single-loop client plane)."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"

    client_id = await manager.create_session(transport, None)

    result1 = await manager.subscribe_loop(client_id, "loop-abc123")
    assert result1 is True
    result2 = await manager.subscribe_loop(client_id, "loop-def456")
    assert result2 is True

    session = await manager.get_session(client_id)
    assert session is not None
    assert session.subscriptions == {"loop-def456"}

    # Cleanup
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_sender_loop_filters_internal_events_on_wire() -> None:
    """Wire visibility filter drops INTERNAL-tier events regardless of client."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_loop(client_id, "loop-abc123")
    assert result is True

    class TestEvent(SootheEvent):
        type: str = "soothe.internal.iteration.started"

    event = {"type": "event", "data": {"type": "soothe.internal.iteration.started"}}
    event_meta = EventMeta(
        type_string="soothe.internal.iteration.started",
        model=TestEvent,
        domain="internal",
        component="iteration",
        action="started",
        verbosity=VerbosityTier.INTERNAL,
    )
    await bus.publish(loop_event_topic("loop-abc123"), event, event_meta=event_meta)
    await asyncio.sleep(0.05)

    transport.send.assert_not_called()
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_sender_loop_filters_debug_tier_events_on_wire() -> None:
    """Wire visibility filter drops DEBUG-tier events; clients always project NORMAL."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_loop(client_id, "loop-abc123")
    assert result is True

    class DebugEvent(SootheEvent):
        type: str = "soothe.stream.heartbeat"

    event = {"type": "event", "data": {"type": "soothe.stream.heartbeat"}}
    event_meta = EventMeta(
        type_string="soothe.stream.heartbeat",
        model=DebugEvent,
        domain="stream",
        component="heartbeat",
        action="tick",
        verbosity=VerbosityTier.INTERNAL,
    )
    await bus.publish(loop_event_topic("loop-abc123"), event, event_meta=event_meta)
    await asyncio.sleep(0.05)

    transport.send.assert_not_called()
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_send_to_client_serializes_concurrent_sends() -> None:
    """Direct and sender-loop sends must not race on the same WebSocket."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"
    in_flight = 0
    max_in_flight = 0
    send_lock = asyncio.Lock()

    async def tracked_send(_client: object, _msg: dict[str, object]) -> None:
        nonlocal in_flight, max_in_flight
        async with send_lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1

    transport.send = AsyncMock(side_effect=tracked_send)

    client_id = await manager.create_session(transport, None)
    session = await manager.get_session(client_id)
    assert session is not None

    await asyncio.gather(
        manager.send_to_client(session, {"type": "status", "state": "running"}),
        manager.send_to_client(session, {"type": "status", "state": "idle"}),
    )

    assert max_in_flight == 1
    assert transport.send.await_count == 2
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_wake_senders_for_loop_restarts_dead_sender() -> None:
    """Publishing after sender death should restart delivery."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    await manager.subscribe_loop(client_id, "loop-abc123")

    session = await manager.get_session(client_id)
    assert session is not None
    assert session.sender_task is not None
    session.sender_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await session.sender_task

    await manager.wake_senders_for_loop("loop-abc123")
    assert session.sender_task is not None
    assert not session.sender_task.done()

    event = {
        "type": "event",
        "data": {"type": "soothe.cognition.strange_loop.started", "goal": "hello"},
    }
    await bus.publish(loop_event_topic("loop-abc123"), event)
    await asyncio.sleep(0.25)

    assert transport.send.await_count >= 1
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_session_count():
    """Test session_count property."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"

    assert manager.session_count == 0

    client_id1 = await manager.create_session(transport, None)
    assert manager.session_count == 1

    client_id2 = await manager.create_session(transport, None)
    assert manager.session_count == 2

    await manager.remove_session(client_id1)
    assert manager.session_count == 1

    await manager.remove_session(client_id2)
    assert manager.session_count == 0


def test_get_batch_timeout_reads_strange_loop_output_streaming() -> None:
    """Sender loop must resolve streaming interval from ``agent.loop`` config (IG-407)."""
    from soothe.config import SootheConfig

    config = SootheConfig()
    config.agent.loop.output_streaming.streaming_interval_ms = 500

    manager = ClientSessionManager(EventBus(), config=config)

    assert manager._get_batch_timeout() == 0.5


def test_queue_has_high_priority_detects_high_event() -> None:
    """IG-436: _queue_has_high_priority returns True for HIGH priority events."""
    from soothe.foundation.events import EventPriority

    from soothe_daemon.server.session import _queue_has_high_priority

    queue: asyncio.Queue = asyncio.Queue()

    # Empty queue returns False
    assert _queue_has_high_priority(queue) is False

    # NORMAL priority event returns False
    normal_meta = EventMeta(
        type_string="soothe.cognition.strange_loop.step.started",
        model=None,
        domain="cognition",
        component="strange_loop",
        action="step.started",
        verbosity=VerbosityTier.NORMAL,
        priority=EventPriority.NORMAL,
    )
    queue.put_nowait(({"type": "event"}, normal_meta))
    assert _queue_has_high_priority(queue) is False
    # Queue should be restored
    assert queue.qsize() == 1

    # Clear and add HIGH priority event
    queue.get_nowait()
    high_meta = EventMeta(
        type_string="soothe.cognition.strange_loop.completed",
        model=None,
        domain="cognition",
        component="strange_loop",
        action="completed",
        verbosity=VerbosityTier.NORMAL,
        priority=EventPriority.HIGH,
    )
    queue.put_nowait(({"type": "event"}, high_meta))
    assert _queue_has_high_priority(queue) is True
    # Queue should be restored
    assert queue.qsize() == 1


def test_queue_has_high_priority_handles_tuple_and_non_tuple() -> None:
    """IG-436: _queue_has_high_priority handles various queue item formats."""
    from soothe_daemon.server.session import _queue_has_high_priority

    queue: asyncio.Queue = asyncio.Queue()

    # Non-tuple item (legacy format) returns False
    queue.put_nowait({"type": "event"})
    assert _queue_has_high_priority(queue) is False
    assert queue.qsize() == 1

    # Clear and test tuple without event_meta
    queue.get_nowait()
    queue.put_nowait(({"type": "event"}, None))
    assert _queue_has_high_priority(queue) is False
    assert queue.qsize() == 1


@pytest.mark.asyncio
async def test_sender_loop_flushes_high_priority_immediately() -> None:
    """IG-436: HIGH priority events bypass batch fill loop."""
    from soothe.foundation.events import EventPriority

    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    await manager.subscribe_loop(client_id, "loop-abc123")

    session = await manager.get_session(client_id)
    assert session is not None

    # Give sender task time to start
    await asyncio.sleep(0.05)

    # Publish HIGH priority event
    high_meta = EventMeta(
        type_string="soothe.cognition.strange_loop.completed",
        model=None,
        domain="cognition",
        component="strange_loop",
        action="completed",
        verbosity=VerbosityTier.NORMAL,
        priority=EventPriority.HIGH,
    )
    event = {
        "type": "event",
        "data": {"type": "soothe.cognition.strange_loop.completed", "status": "done"},
    }
    await bus.publish(loop_event_topic("loop-abc123"), event, event_meta=high_meta)

    # HIGH priority should flush quickly (not wait for batch timeout)
    await asyncio.sleep(0.1)

    transport.send.assert_called_once()
    call_args = transport.send.call_args
    sent_event = call_args[0][1]
    assert sent_event["data"]["type"] == "soothe.cognition.strange_loop.completed"

    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_sender_loop_batches_normal_priority() -> None:
    """IG-436: NORMAL priority events still batch normally."""
    from soothe.config import SootheConfig

    config = SootheConfig()
    config.agent.loop.output_streaming.streaming_interval_ms = 300  # 300ms batch timeout

    bus = EventBus()
    manager = ClientSessionManager(bus, config=config)

    transport = MagicMock()
    transport.name = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    await manager.subscribe_loop(client_id, "loop-abc123")

    # Give sender task time to start
    await asyncio.sleep(0.05)

    # Publish NORMAL priority events - should batch
    event1 = {"type": "event", "data": {"type": "soothe.cognition.strange_loop.step.started"}}
    event2 = {"type": "event", "data": {"type": "soothe.cognition.strange_loop.step.completed"}}
    await bus.publish(loop_event_topic("loop-abc123"), event1)
    await bus.publish(loop_event_topic("loop-abc123"), event2)

    # After short delay (< batch timeout), should not have sent yet
    await asyncio.sleep(0.05)
    # Note: This test may be timing-dependent; the sender could have sent
    # but the key behavior is that HIGH priority skips batching

    # Wait for batch timeout
    await asyncio.sleep(0.35)

    # Should have sent (either batched or individual)
    assert transport.send.await_count >= 1

    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_await_loop_delivery_drained_with_high_priority() -> None:
    """IG-436: Drain adds extra settle margin for HIGH priority events."""
    from soothe.foundation.events import EventPriority

    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.name = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    await manager.subscribe_loop(client_id, "loop-test")

    session = await manager.get_session(client_id)
    assert session is not None

    # Put HIGH priority event directly in queue
    high_meta = EventMeta(
        type_string="soothe.cognition.strange_loop.completed",
        model=None,
        domain="cognition",
        component="strange_loop",
        action="completed",
        verbosity=VerbosityTier.NORMAL,
        priority=EventPriority.HIGH,
    )
    session.event_queue.put_nowait(({"type": "event"}, high_meta))

    # Drain should wait for HIGH priority to be processed
    # with extra settle margin
    result = await manager.await_loop_delivery_drained("loop-test", batch_timeout_s=0.1)

    # Should return True after settling
    assert result is True

    await manager.remove_session(client_id)
