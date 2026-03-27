"""Unit tests for EventBus."""

import asyncio

import pytest

from soothe.daemon.event_bus import EventBus


@pytest.mark.asyncio
async def test_publish_to_single_subscriber():
    """Test publishing event to one subscriber."""
    bus = EventBus()
    queue: asyncio.Queue[dict[str, any]] = asyncio.Queue()

    await bus.subscribe("thread:abc123", queue)

    event = {"type": "test", "data": "hello"}
    await bus.publish("thread:abc123", event)

    received_data = await queue.get()
    # RFC-0022: EventBus now returns (event, event_meta) tuple
    assert isinstance(received_data, tuple)
    received_event, received_meta = received_data
    assert received_event == event
    assert received_meta is None  # No metadata provided


@pytest.mark.asyncio
async def test_publish_to_multiple_subscribers():
    """Test publishing event to multiple subscribers."""
    bus = EventBus()
    queue1: asyncio.Queue[dict[str, any]] = asyncio.Queue()
    queue2: asyncio.Queue[dict[str, any]] = asyncio.Queue()

    await bus.subscribe("thread:abc123", queue1)
    await bus.subscribe("thread:abc123", queue2)

    event = {"type": "test", "data": "hello"}
    await bus.publish("thread:abc123", event)

    # RFC-0022: EventBus now returns (event, event_meta) tuple
    received1 = await queue1.get()
    received2 = await queue2.get()
    assert isinstance(received1, tuple) and isinstance(received2, tuple)
    assert received1[0] == event
    assert received2[0] == event


@pytest.mark.asyncio
async def test_unsubscribe():
    """Test unsubscribing from topic."""
    bus = EventBus()
    queue: asyncio.Queue[dict[str, any]] = asyncio.Queue()

    await bus.subscribe("thread:abc123", queue)
    await bus.unsubscribe("thread:abc123", queue)

    event = {"type": "test", "data": "hello"}
    await bus.publish("thread:abc123", event)

    # Queue should be empty
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_unsubscribe_all():
    """Test unsubscribing from all topics."""
    bus = EventBus()
    queue: asyncio.Queue[dict[str, any]] = asyncio.Queue()

    await bus.subscribe("thread:abc123", queue)
    await bus.subscribe("thread:def456", queue)
    await bus.unsubscribe_all(queue)

    # Queue should not receive any events
    await bus.publish("thread:abc123", {"type": "test1"})
    await bus.publish("thread:def456", {"type": "test2"})

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_queue_overflow():
    """Test that events are dropped when queue is full."""
    bus = EventBus()
    # Queue with maxsize=1
    queue: asyncio.Queue[dict[str, any]] = asyncio.Queue(maxsize=1)

    await bus.subscribe("thread:abc123", queue)

    # Send 3 events, only first should be delivered
    for i in range(3):
        await bus.publish("thread:abc123", {"type": "test", "data": i})

    # Only one event in queue
    received_data = await queue.get()
    # RFC-0022: EventBus now returns (event, event_meta) tuple
    assert isinstance(received_data, tuple)
    event, _ = received_data
    assert event["data"] == 0

    # Queue is now empty (overflow events dropped)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_no_subscribers():
    """Test publishing to topic with no subscribers."""
    bus = EventBus()

    # Should not raise an error
    await bus.publish("thread:abc123", {"type": "test"})


@pytest.mark.asyncio
async def test_multiple_topics():
    """Test that subscribers only receive events for their topic."""
    bus = EventBus()
    queue1: asyncio.Queue[dict[str, any]] = asyncio.Queue()
    queue2: asyncio.Queue[dict[str, any]] = asyncio.Queue()

    await bus.subscribe("thread:abc123", queue1)
    await bus.subscribe("thread:def456", queue2)

    await bus.publish("thread:abc123", {"type": "test1"})
    await bus.publish("thread:def456", {"type": "test2"})

    # Each queue only gets its own topic
    # RFC-0022: EventBus now returns (event, event_meta) tuple
    received1 = await queue1.get()
    received2 = await queue2.get()
    assert isinstance(received1, tuple) and isinstance(received2, tuple)
    event1, _ = received1
    event2, _ = received2
    assert event1["type"] == "test1"
    assert event2["type"] == "test2"

    # Queues should be empty
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue1.get(), timeout=0.1)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue2.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_topic_count():
    """Test topic_count property."""
    bus = EventBus()
    queue: asyncio.Queue[dict[str, any]] = asyncio.Queue()

    assert bus.topic_count == 0

    await bus.subscribe("thread:abc123", queue)
    assert bus.topic_count == 1

    await bus.subscribe("thread:def456", queue)
    assert bus.topic_count == 2

    await bus.unsubscribe("thread:abc123", queue)
    assert bus.topic_count == 1

    await bus.unsubscribe("thread:def456", queue)
    assert bus.topic_count == 0
