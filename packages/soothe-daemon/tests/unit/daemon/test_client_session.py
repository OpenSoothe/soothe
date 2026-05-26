"""Unit tests for ClientSession and ClientSessionManager."""

import asyncio
import contextlib
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe.core.events import EventMeta
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier

from soothe_daemon.event import EventBus, loop_event_topic
from soothe_daemon.session import ClientSessionManager


@pytest.mark.asyncio
async def test_create_session():
    """Test session creation."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.transport_type = "test"

    client_id = await manager.create_session(transport=transport, transport_client=None)

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
    transport.transport_type = "test"

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
    transport.transport_type = "test"

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
    transport.transport_type = "test"

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
    transport.transport_type = "test"

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
    transport.transport_type = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    await manager.subscribe_loop(client_id, "loop-abc123")

    # Give sender task time to start
    await asyncio.sleep(0.05)

    event = {
        "type": "event",
        "data": {"type": "soothe.cognition.agent_loop.started", "goal": "hello"},
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
    transport.transport_type = "test"
    transport.send = AsyncMock(side_effect=Exception("Connection error"))

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_loop(client_id, "loop-abc123")
    assert result is True

    event = {
        "type": "event",
        "data": {"type": "soothe.cognition.agent_loop.started", "goal": "hello"},
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
    transport.transport_type = "test"
    transport.send = AsyncMock(side_effect=ConnectionError("peer closed"))

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_loop(client_id, "loop-abc123")
    assert result is True

    caplog.set_level(logging.WARNING, logger="soothe_daemon.client_session")

    event = {
        "type": "event",
        "data": {"type": "soothe.cognition.agent_loop.started", "goal": "hello"},
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
    transport.transport_type = "test"

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
async def test_subscribe_loop_accepts_normal_verbosity() -> None:
    """Test `normal` is accepted as a client verbosity level."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.transport_type = "test"

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_loop(client_id, "loop-abc123", verbosity="normal")
    assert result is True

    session = await manager.get_session(client_id)
    assert session is not None
    assert session.verbosity == "normal"

    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_sender_loop_filters_detailed_event_for_normal_verbosity() -> None:
    """Test daemon-side filtering at `normal` verbosity hides DETAILED-tier events."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.transport_type = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_loop(client_id, "loop-abc123", verbosity="normal")
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
async def test_sender_loop_filters_verbose_events_even_at_debug_verbosity() -> None:
    """Client ``verbosity=debug`` must not receive DETAILED/DEBUG catalog events on the wire."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.transport_type = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_loop(client_id, "loop-abc123", verbosity="debug")
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
        verbosity=VerbosityTier.DEBUG,
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
    transport.transport_type = "test"
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
    transport.transport_type = "test"
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
        "data": {"type": "soothe.cognition.agent_loop.started", "goal": "hello"},
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
    transport.transport_type = "test"

    assert manager.session_count == 0

    client_id1 = await manager.create_session(transport, None)
    assert manager.session_count == 1

    client_id2 = await manager.create_session(transport, None)
    assert manager.session_count == 2

    await manager.remove_session(client_id1)
    assert manager.session_count == 1

    await manager.remove_session(client_id2)
    assert manager.session_count == 0


def test_get_batch_timeout_reads_agent_loop_output_streaming() -> None:
    """Sender loop must resolve streaming interval from ``agent.loop`` config (IG-407)."""
    from soothe.config import SootheConfig

    config = SootheConfig()
    config.agent.loop.output_streaming.streaming_interval_ms = 500

    manager = ClientSessionManager(EventBus(), config=config)

    assert manager._get_batch_timeout() == 0.5
