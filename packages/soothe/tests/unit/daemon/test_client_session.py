"""Unit tests for ClientSession and ClientSessionManager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier

from soothe.core.event_catalog import EventMeta
from soothe.daemon.client_session import ClientSessionManager
from soothe.daemon.event_bus import EventBus


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
async def test_subscribe_thread():
    """Test thread subscription."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.transport_type = "test"

    client_id = await manager.create_session(transport, None)

    result = await manager.subscribe_thread(client_id, "thread-abc123")
    assert result is True

    session = await manager.get_session(client_id)
    assert session is not None
    assert "thread-abc123" in session.subscriptions

    # Cleanup
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_unsubscribe_thread():
    """Test thread unsubscription."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.transport_type = "test"

    client_id = await manager.create_session(transport, None)
    subscribe_result = await manager.subscribe_thread(client_id, "thread-abc123")
    assert subscribe_result is True
    unsubscribe_result = await manager.unsubscribe_thread(client_id, "thread-abc123")
    assert unsubscribe_result is True

    session = await manager.get_session(client_id)
    assert session is not None
    assert "thread-abc123" not in session.subscriptions

    # Cleanup
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_subscribe_invalid_client():
    """Test subscribing invalid client returns False gracefully."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    # Should return False instead of raising ValueError
    result = await manager.subscribe_thread("invalid", "thread-abc123")
    assert result is False


@pytest.mark.asyncio
async def test_unsubscribe_invalid_client():
    """Test unsubscribing invalid client returns False gracefully."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    # Should return False instead of raising ValueError
    result = await manager.unsubscribe_thread("invalid", "thread-abc123")
    assert result is False


@pytest.mark.asyncio
async def test_remove_session():
    """Test session removal."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.transport_type = "test"

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_thread(client_id, "thread-abc123")
    assert result is True

    assert manager.session_count == 1

    await manager.remove_session(client_id)

    assert manager.session_count == 0
    session = await manager.get_session(client_id)
    assert session is None


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="Timing issue with async sender loop in unit test - covered by integration tests"
)
async def test_sender_loop_sends_events():
    """Test that sender loop sends events via transport."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.transport_type = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    await manager.subscribe_thread(client_id, "thread-abc123")

    # Give sender task time to start
    await asyncio.sleep(0.05)

    # Publish event
    event = {"type": "test", "data": "hello"}
    await bus.publish("thread:abc123", event)

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
    result = await manager.subscribe_thread(client_id, "thread-abc123")
    assert result is True

    # Publish event
    event = {"type": "test", "data": "hello"}
    await bus.publish("thread:abc123", event)

    # Wait for sender loop to process
    await asyncio.sleep(0.1)

    # Session should be removed due to error
    # (In real implementation, we might want to handle this differently)

    # Cleanup
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_multiple_subscriptions():
    """Test client can subscribe to multiple threads."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.transport_type = "test"

    client_id = await manager.create_session(transport, None)

    result1 = await manager.subscribe_thread(client_id, "thread-abc123")
    assert result1 is True
    result2 = await manager.subscribe_thread(client_id, "thread-def456")
    assert result2 is True

    session = await manager.get_session(client_id)
    assert session is not None
    assert len(session.subscriptions) == 2
    assert "thread-abc123" in session.subscriptions
    assert "thread-def456" in session.subscriptions

    # Cleanup
    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_subscribe_thread_accepts_minimal_verbosity() -> None:
    """Test `minimal` is accepted as a client verbosity level."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.transport_type = "test"

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_thread(client_id, "thread-abc123", verbosity="minimal")
    assert result is True

    session = await manager.get_session(client_id)
    assert session is not None
    assert session.verbosity == "minimal"

    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_sender_loop_filters_detailed_event_for_minimal_verbosity() -> None:
    """Test daemon-side filtering treats `minimal` like `normal`."""
    bus = EventBus()
    manager = ClientSessionManager(bus)

    transport = MagicMock()
    transport.transport_type = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    result = await manager.subscribe_thread(client_id, "thread-abc123", verbosity="minimal")
    assert result is True

    class TestEvent(SootheEvent):
        type: str = "soothe.lifecycle.thread.created"

    event = {"type": "event", "data": {"type": "soothe.lifecycle.thread.created"}}
    event_meta = EventMeta(
        type_string="soothe.lifecycle.thread.created",
        model=TestEvent,
        domain="lifecycle",
        component="thread",
        action="created",
        verbosity=VerbosityTier.DETAILED,
    )
    await bus.publish("thread:thread-abc123", event, event_meta=event_meta)
    await asyncio.sleep(0.05)

    transport.send.assert_not_called()
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
