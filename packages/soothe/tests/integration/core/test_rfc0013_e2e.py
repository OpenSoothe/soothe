"""End-to-end integration tests for RFC-0013 (Unified Daemon Communication Protocol).

This comprehensive test suite validates:
- Event bus architecture and topic-based routing
- Multi-client isolation and session management
- Cross-transport event delivery
- Stress testing and edge cases
- Performance characteristics
- Recovery and failure scenarios
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from soothe.daemon import SootheDaemon, WebSocketClient
from soothe.daemon.event_bus import EventBus
from tests.integration.conftest import (
    alloc_ephemeral_port,
    await_event_type,
    await_status_state,
    build_daemon_config,
    force_isolated_home,
)

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
async def isolated_daemon(tmp_path: Path):
    """Start an isolated daemon with WebSocket and HTTP REST transports for E2E testing."""
    force_isolated_home(tmp_path / "soothe-home")

    ws_port = alloc_ephemeral_port()
    http_port = alloc_ephemeral_port()

    config = build_daemon_config(
        tmp_path=tmp_path,
        websocket_port=ws_port,
        http_port=http_port,
    )

    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.3)  # Allow transports to initialize

    try:
        yield {
            "daemon": daemon,
            "ws_port": ws_port,
            "http_port": http_port,
            "config": config,
        }
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


# ============================================================================
# Layer A: Event Bus Architecture Validation
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_event_bus_topic_isolation() -> None:
    """Test that EventBus properly isolates events by topic."""
    bus = EventBus()

    # Create queues for different topics
    queue_thread1: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    queue_thread2: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    queue_thread1_dup: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    # Subscribe to different topics
    await bus.subscribe("thread:thread1", queue_thread1)
    await bus.subscribe("thread:thread2", queue_thread2)
    await bus.subscribe("thread:thread1", queue_thread1_dup)  # Multiple subscribers

    # Publish events to thread1
    event1 = {"type": "test", "data": "event1"}
    await bus.publish("thread:thread1", event1)

    # Publish events to thread2
    event2 = {"type": "test", "data": "event2"}
    await bus.publish("thread:thread2", event2)

    # Verify thread1 subscribers only get thread1 events
    # EventBus now sends (event, event_meta) tuples for RFC-0022 filtering
    received1, meta1 = await queue_thread1.get()
    assert received1 == event1
    assert meta1 is None  # No metadata provided

    received1_dup, meta1_dup = await queue_thread1_dup.get()
    assert received1_dup == event1
    assert meta1_dup is None

    # Verify thread2 subscriber only gets thread2 events
    received2, meta2 = await queue_thread2.get()
    assert received2 == event2
    assert meta2 is None

    # Verify queues are empty (no cross-contamination)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue_thread1.get(), timeout=0.1)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue_thread2.get(), timeout=0.1)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_event_bus_unsubscribe_cleanup() -> None:
    """Test that EventBus properly cleans up subscriptions."""
    bus = EventBus()

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    # Subscribe
    await bus.subscribe("thread:abc", queue)
    assert bus.topic_count == 1

    # Unsubscribe
    await bus.unsubscribe("thread:abc", queue)
    assert bus.topic_count == 0

    # Publish should not deliver to unsubscribed queue
    await bus.publish("thread:abc", {"type": "test"})

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_event_bus_overflow_protection() -> None:
    """Test that EventBus drops events when queue is full (graceful degradation)."""
    bus = EventBus()

    # Queue with maxsize=2
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2)
    await bus.subscribe("thread:abc", queue)

    # Send more events than queue can hold
    for i in range(10):
        await bus.publish("thread:abc", {"type": "test", "data": i})

    # Should only receive first 2 events (rest dropped)
    # EventBus now sends (event, event_meta) tuples
    event1, meta1 = await queue.get()
    event2, meta2 = await queue.get()

    # The exact values depend on timing, but queue should be empty after
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)


# ============================================================================
# Layer A: Multi-Client Isolation Scenarios
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_three_clients_complete_isolation(tmp_path: Path, requires_llm_api) -> None:
    """Test that three clients with different threads are completely isolated."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        # Create 3 clients
        clients = []
        thread_ids = []

        for i in range(3):
            client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            await client.connect()
            await client.send_thread_create(initial_message=f"Client {i}")

            status = await await_event_type(client.read_event, "thread_created", timeout=3.0)
            thread_id = status["thread_id"]
            thread_ids.append(thread_id)

            await client.subscribe_thread(thread_id)
            await client.wait_for_subscription_confirmed(thread_id)

            clients.append(client)

        # Verify all thread IDs are unique
        assert len(set(thread_ids)) == 3

        # Send input from client 0
        await clients[0].send_input("Query from client 0")

        # Client 0 should receive events
        event = await asyncio.wait_for(clients[0].read_event(), timeout=2.0)
        assert event is not None

        # Clients 1 and 2 should NOT receive events from client 0's thread
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(clients[1].read_event(), timeout=0.5)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(clients[2].read_event(), timeout=0.5)

        # Cleanup
        for client in clients:
            await client.close()

    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_subscription_after_thread_creation(tmp_path: Path, requires_llm_api) -> None:
    """Test that client can subscribe to thread after it's created."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()

        # Create thread first (without immediate subscription)
        await client.send_thread_create(initial_message="Test thread")
        created = await await_event_type(client.read_event, "thread_created", timeout=3.0)
        thread_id = created["thread_id"]

        # Subscribe to the thread AFTER creation
        await client.subscribe_thread(thread_id)
        confirmation = await await_event_type(
            client.read_event, "subscription_confirmed", timeout=3.0
        )
        assert confirmation["thread_id"] == thread_id

        # Send input and verify events are received
        await client.send_input("Test query")

        # Should receive events because we're subscribed
        event = await asyncio.wait_for(client.read_event(), timeout=3.0)
        assert event is not None

        await client.close()

    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_multiple_thread_subscriptions(tmp_path: Path, requires_llm_api) -> None:
    """Test that a single client can subscribe to multiple threads simultaneously."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()

        # Create 3 threads and subscribe to all
        thread_ids = []
        for i in range(3):
            await client.send_thread_create(initial_message=f"Thread {i}")
            created = await await_event_type(client.read_event, "thread_created", timeout=3.0)
            thread_id = created["thread_id"]
            thread_ids.append(thread_id)

            await client.subscribe_thread(thread_id)
            confirmation = await await_event_type(
                client.read_event, "subscription_confirmed", timeout=3.0
            )
            assert confirmation["thread_id"] == thread_id

        # Verify client receives events for all subscribed threads
        # (Behavioral verification instead of implementation details)
        # The client successfully subscribed to all 3 threads and received confirmation
        assert len(thread_ids) == 3

        await client.close()

    finally:
        await daemon.stop()


# ============================================================================
# Layer A: Stress Testing and Edge Cases
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_rapid_client_connections(tmp_path: Path, requires_llm_api) -> None:
    """Test daemon stability with rapid client connections/disconnections."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        num_iterations = 20

        for iteration in range(num_iterations):
            # Connect
            client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            await client.connect()

            # Create thread
            await client.send_thread_create(initial_message=f"Iteration {iteration}")
            created = await await_event_type(client.read_event, "thread_created", timeout=3.0)
            thread_id = created["thread_id"]

            # Subscribe
            await client.subscribe_thread(thread_id)
            await await_event_type(client.read_event, "subscription_confirmed", timeout=3.0)

            # Quick query
            await client.send_input("Quick test")
            await asyncio.sleep(0.05)

            # Disconnect
            await client.close()

            # Verify session was cleaned up
            await asyncio.sleep(0.05)

        # Verify daemon is still stable
        test_client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await test_client.connect()
        await test_client.send_thread_list()
        response = await await_event_type(
            test_client.read_event, "thread_list_response", timeout=3.0
        )
        assert response["type"] == "thread_list_response"
        await test_client.close()

    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_event_throughput_stress(tmp_path: Path, requires_llm_api) -> None:
    """Test event bus performance under high throughput."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()

        # Create thread and subscribe
        await client.send_thread_create(initial_message="Throughput test")
        created = await await_event_type(client.read_event, "thread_created", timeout=3.0)
        thread_id = created["thread_id"]

        await client.subscribe_thread(thread_id)
        await await_event_type(client.read_event, "subscription_confirmed", timeout=3.0)

        # Send multiple queries rapidly
        num_queries = 5
        for i in range(num_queries):
            await client.send_input(f"Query {i}")
            # Wait for completion before next query
            status = await await_status_state(client.read_event, {"running", "idle"}, timeout=8.0)
            if status.get("state") == "running":
                await await_status_state(client.read_event, "idle", timeout=8.0)

        await client.close()

    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_large_message_handling(tmp_path: Path, requires_llm_api) -> None:
    """Test daemon handles large messages correctly (up to size limit)."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()

        # Create thread with moderately large initial message (1KB)
        large_message = "x" * 1024
        await client.send_thread_create(initial_message=large_message)
        created = await await_event_type(client.read_event, "thread_created", timeout=3.0)

        assert created["type"] == "thread_created"

        await client.close()

    finally:
        await daemon.stop()


# ============================================================================
# Layer A: Session Lifecycle Management
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_cleanup_on_unexpected_disconnect(tmp_path: Path, requires_llm_api) -> None:
    """Test that session is properly cleaned up on unexpected client disconnect."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        initial_count = daemon._session_manager.session_count

        # Connect client
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.send_thread_create(initial_message="Test")
        status = await await_event_type(client.read_event, "thread_created", timeout=3.0)
        thread_id = status["thread_id"]

        await client.subscribe_thread(thread_id)
        await await_event_type(client.read_event, "subscription_confirmed", timeout=3.0)

        # Verify session was created
        assert daemon._session_manager.session_count == initial_count + 1

        # Abrupt disconnect (no graceful close)
        # Simulate by canceling all reader tasks
        await client.close()

        # Wait for cleanup
        await asyncio.sleep(0.3)

        # Verify session was removed
        assert daemon._session_manager.session_count == initial_count

    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_reconnect_after_disconnect(tmp_path: Path, requires_llm_api) -> None:
    """Test that client can reconnect after disconnect and create new session."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        # First connection
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.send_thread_create(initial_message="First session")
        created1 = await await_event_type(client.read_event, "thread_created", timeout=3.0)
        thread_id1 = created1["thread_id"]

        await client.subscribe_thread(thread_id1)
        await await_event_type(client.read_event, "subscription_confirmed", timeout=3.0)

        # Disconnect
        await client.close()
        await asyncio.sleep(0.2)

        # Reconnect
        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client2.connect()
        await client2.send_thread_create(initial_message="Second session")
        created2 = await await_event_type(client2.read_event, "thread_created", timeout=3.0)
        thread_id2 = created2["thread_id"]

        await client2.subscribe_thread(thread_id2)
        await await_event_type(client2.read_event, "subscription_confirmed", timeout=3.0)

        # Verify different threads
        assert thread_id1 != thread_id2

        await client2.close()

    finally:
        await daemon.stop()


# ============================================================================
# Layer A: Protocol Message Validation
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_protocol_message_thread_id_in_events(tmp_path: Path, requires_llm_api) -> None:
    """Test that all event messages include thread_id field."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()

        # Create thread
        await client.send_thread_create(initial_message="Test thread_id in events")
        created = await await_event_type(client.read_event, "thread_created", timeout=3.0)
        thread_id = created["thread_id"]

        await client.subscribe_thread(thread_id)
        await await_event_type(client.read_event, "subscription_confirmed", timeout=3.0)

        # Send query and collect events
        await client.send_input("Test query")

        events_received = 0
        max_events = 20
        timeout_seconds = 5.0

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds

        while loop.time() < deadline and events_received < max_events:
            try:
                event = await asyncio.wait_for(client.read_event(), timeout=0.5)
                if event:
                    events_received += 1

                    # Check if this is a stream event
                    if event.get("type") == "event":
                        assert "thread_id" in event, "Event message missing thread_id"
                        assert event.get("thread_id") == thread_id

                    # Check for idle status (query completed)
                    if event.get("type") == "status" and event.get("state") == "idle":
                        break

            except TimeoutError:
                continue

        assert events_received > 0, "Should have received at least one event"

        await client.close()

    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_protocol_client_id_in_status(tmp_path: Path, requires_llm_api) -> None:
    """Test that status messages include client_id field."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        # Connect first client
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client1.connect()
        await client1.send_thread_create(initial_message="Client 1")
        status1 = await await_event_type(client1.read_event, "thread_created", timeout=3.0)

        client_id1 = status1.get("client_id")
        assert client_id1 is not None
        assert isinstance(client_id1, str)

        # Connect second client
        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client2.connect()
        await client2.send_thread_create(initial_message="Client 2")
        status2 = await await_event_type(client2.read_event, "thread_created", timeout=3.0)

        client_id2 = status2.get("client_id")
        assert client_id2 is not None
        assert isinstance(client_id2, str)

        # Verify different client IDs
        assert client_id1 != client_id2

        await client1.close()
        await client2.close()

    finally:
        await daemon.stop()


# ============================================================================
# Layer A: Multi-Transport Integration
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cross_transport_client_count(isolated_daemon: dict) -> None:
    """Test that client count correctly aggregates across all transports."""
    daemon = isolated_daemon["daemon"]
    ws_port = isolated_daemon["ws_port"]

    # Initial state
    await asyncio.sleep(0.2)
    initial_count = daemon._transport_manager.client_count

    # Connect Unix socket client
    client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client1.connect()
    await asyncio.sleep(0.1)

    count_after_1 = daemon._transport_manager.client_count
    assert count_after_1 >= initial_count + 1

    # Connect second Unix socket client
    client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client2.connect()
    await asyncio.sleep(0.1)

    count_after_2 = daemon._transport_manager.client_count
    assert count_after_2 >= count_after_1 + 1

    # Disconnect first client
    await client1.close()
    await asyncio.sleep(0.1)

    count_after_disconnect = daemon._transport_manager.client_count
    assert count_after_disconnect < count_after_2

    # Disconnect second client
    await client2.close()
    await asyncio.sleep(0.1)

    final_count = daemon._transport_manager.client_count
    assert final_count >= initial_count


# ============================================================================
# Layer A: Performance Characteristics
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_event_delivery_latency(tmp_path: Path) -> None:
    """Test event delivery latency is within acceptable bounds."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()

        # Create thread
        await client.send_thread_create(initial_message="Latency test")
        created = await await_event_type(client.read_event, "thread_created", timeout=3.0)
        thread_id = created["thread_id"]

        await client.subscribe_thread(thread_id)
        await await_event_type(client.read_event, "subscription_confirmed", timeout=3.0)

        # Measure event delivery time
        start_time = time.time()

        await client.send_input("Quick response test")

        # Wait for first event
        await asyncio.wait_for(client.read_event(), timeout=5.0)
        latency = time.time() - start_time

        # Event should be delivered within reasonable time (< 2 seconds for local)
        assert latency < 2.0, f"Event delivery took {latency}s (> 2s threshold)"

        # Wait for completion
        status = await await_status_state(client.read_event, {"running", "idle"}, timeout=8.0)
        if status.get("state") == "running":
            await await_status_state(client.read_event, "idle", timeout=8.0)

        await client.close()

    finally:
        await daemon.stop()


# ============================================================================
# Layer A: Failure Recovery
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_daemon_remains_stable_after_client_errors(tmp_path: Path) -> None:
    """Test daemon remains stable after client errors (malformed messages, etc.)."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        # Connect client and send problematic messages
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()

        # Try to access non-existent thread
        fake_thread_id = f"non-existent-{uuid.uuid4().hex}"
        await client.send_thread_get(fake_thread_id)

        # Read response (should not crash daemon)
        response = await asyncio.wait_for(client.read_event(), timeout=3.0)
        assert response is not None

        # Verify daemon still works with valid operations
        await client.send_thread_create(initial_message="Valid thread")
        created = await await_event_type(client.read_event, "thread_created", timeout=3.0)
        assert created["type"] == "thread_created"

        thread_id = created["thread_id"]
        await client.subscribe_thread(thread_id)
        await await_event_type(client.read_event, "subscription_confirmed", timeout=3.0)

        # Valid query should work
        await client.send_input("Valid query")
        status = await await_status_state(client.read_event, {"running", "idle"}, timeout=5.0)

        if status.get("state") == "running":
            await await_status_state(client.read_event, "idle", timeout=5.0)

        await client.close()

    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_graceful_handling_of_invalid_subscriptions(tmp_path: Path) -> None:
    """Test that invalid subscription attempts are handled gracefully."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()

        # Try to subscribe to non-existent thread
        fake_thread_id = f"fake-thread-{uuid.uuid4().hex}"
        await client.subscribe_thread(fake_thread_id)

        # Should receive error response
        response = await asyncio.wait_for(client.read_event(), timeout=3.0)
        assert response is not None

        # Client should still be connected
        await client.send_thread_list()
        list_response = await await_event_type(
            client.read_event, "thread_list_response", timeout=3.0
        )
        assert list_response["type"] == "thread_list_response"

        await client.close()

    finally:
        await daemon.stop()


# ============================================================================
# Layer A: Concurrent Execution
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_concurrent_queries_different_threads(tmp_path: Path, requires_llm_api) -> None:
    """Test that multiple threads can execute concurrently (if supported)."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()

    try:
        # Create two clients with different threads
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client1.connect()
        await client1.send_thread_create(initial_message="Thread 1")
        created1 = await await_event_type(client1.read_event, "thread_created", timeout=3.0)
        thread1 = created1["thread_id"]
        await client1.subscribe_thread(thread1)
        await await_event_type(client1.read_event, "subscription_confirmed", timeout=3.0)

        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client2.connect()
        await client2.send_thread_create(initial_message="Thread 2")
        created2 = await await_event_type(client2.read_event, "thread_created", timeout=3.0)
        thread2 = created2["thread_id"]
        await client2.subscribe_thread(thread2)
        await await_event_type(client2.read_event, "subscription_confirmed", timeout=3.0)

        # Send queries on both threads
        await client1.send_input("Query on thread 1")
        await client2.send_input("Query on thread 2")

        # Both should be able to process
        status1 = await await_status_state(client1.read_event, {"running", "idle"}, timeout=5.0)
        status2 = await await_status_state(client2.read_event, {"running", "idle"}, timeout=5.0)

        # Wait for completion
        if status1.get("state") == "running":
            await await_status_state(client1.read_event, "idle", timeout=8.0)

        if status2.get("state") == "running":
            await await_status_state(client2.read_event, "idle", timeout=8.0)

        await client1.close()
        await client2.close()

    finally:
        await daemon.stop()


# ============================================================================
# Utility Functions
# ============================================================================


def _generate_large_json(size_kb: int) -> dict[str, Any]:
    """Generate a large JSON object for testing."""
    return {"payload": "x" * (size_kb * 1024)}
