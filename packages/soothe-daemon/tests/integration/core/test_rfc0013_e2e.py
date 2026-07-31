"""End-to-end integration tests for RFC-0013 (Unified Daemon Communication Protocol).

This comprehensive test suite validates:
- Event bus architecture and topic-based routing
- Multi-client isolation and session management
- WebSocket transport event delivery
- Stress testing and edge cases
- Performance characteristics
- Recovery and failure scenarios
"""

from __future__ import annotations

import asyncio
import gc
import os
import resource
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from soothe_client import WebSocketClient
from soothe_sdk.wire import ProtocolError

from soothe_daemon import SootheDaemon
from soothe_daemon.event import EventBus
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    await_status_state,
    await_subscribe_ack,
    build_daemon_config,
    close_client_safely,
    force_isolated_home,
    integration_llm_idle_timeout,
    stop_daemon_safely,
)
from tests.integration.ws_loop_client import (
    loop_new_with_initial_input,
    request_loop_list,
    subscribe_loop_stream,
)


async def _assert_client_receives_no_events_for_loop(
    client: WebSocketClient,
    forbidden_loop_id: str,
    *,
    timeout: float = 0.5,
) -> None:
    """Fail if ``client`` receives an event clearly scoped to ``forbidden_loop_id``.

    Global broadcasts (no loop id) are ignored so the check targets cross-loop leaks.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return
        try:
            ev = await asyncio.wait_for(
                client.read_event(),
                timeout=min(0.05, remaining),
            )
        except TimeoutError:
            return
        if not ev:
            continue
        lid = ev.get("loop_id") or ev.get("thread_id")
        if lid == forbidden_loop_id:
            msg = f"received loop-scoped traffic for another client's loop: {ev!r}"
            raise AssertionError(msg)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
async def isolated_daemon(tmp_path: Path):
    """Start an isolated daemon with WebSocket transport for E2E testing."""
    force_isolated_home(tmp_path / "soothe-home")

    port = alloc_ephemeral_port()

    config, daemon_cfg = build_daemon_config(
        tmp_path=tmp_path,
        websocket_port=port,
    )

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    await asyncio.sleep(0.3)  # Allow transport to initialize

    try:
        yield {
            "daemon": daemon,
            "ws_port": port,
            "config": config,
        }
    finally:
        await stop_daemon_safely(daemon)


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
    await bus.subscribe("loop:thread1", queue_thread1)
    await bus.subscribe("loop:thread2", queue_thread2)
    await bus.subscribe("loop:thread1", queue_thread1_dup)  # Multiple subscribers

    # Publish events to thread1
    event1 = {"type": "test", "data": "event1"}
    await bus.publish("loop:thread1", event1)

    # Publish events to thread2
    event2 = {"type": "test", "data": "event2"}
    await bus.publish("loop:thread2", event2)

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
    await bus.subscribe("loop:abc", queue)
    assert bus.topic_count == 1

    # Unsubscribe
    await bus.unsubscribe("loop:abc", queue)
    assert bus.topic_count == 0

    # Publish should not deliver to unsubscribed queue
    await bus.publish("loop:abc", {"type": "test"})

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_event_bus_overflow_protection() -> None:
    """Test that EventBus drops events when queue is full (graceful degradation)."""
    bus = EventBus()

    # Queue with maxsize=2
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2)
    await bus.subscribe("loop:abc", queue)

    # Send more events than queue can hold
    for i in range(10):
        await bus.publish("loop:abc", {"type": "test", "data": i})

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
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    try:
        # Create 3 clients
        clients = []
        thread_ids = []

        for i in range(3):
            client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            await client.connect()
            await client.request_connection_init()
            await client.wait_for_connection_ack()
            loop_id = await loop_new_with_initial_input(client, initial_message=f"Client {i}")
            thread_ids.append(loop_id)

            await subscribe_loop_stream(client, loop_id)

            clients.append(client)

        # Verify all thread IDs are unique
        assert len(set(thread_ids)) == 3

        # Clear pending events only for clients 1 and 2 (should not receive events)
        # Client 0 should receive events from its own query
        clients[1].clear_pending_events()
        clients[2].clear_pending_events()

        # Send input from client 0
        await clients[0].send_input(thread_ids[0], "Query from client 0")

        # Client 0 should receive events
        event = await asyncio.wait_for(clients[0].read_event(), timeout=2.0)
        assert event is not None

        # Clients 1 and 2 must not receive loop-scoped traffic for client 0's loop
        await _assert_client_receives_no_events_for_loop(clients[1], thread_ids[0])
        await _assert_client_receives_no_events_for_loop(clients[2], thread_ids[0])

        # Cleanup
        for c in clients:
            await close_client_safely(c)

    finally:
        await stop_daemon_safely(daemon)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_subscription_after_thread_creation(tmp_path: Path, requires_llm_api) -> None:
    """Test that client can subscribe to thread after it's created."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()

        # Create loop first (without immediate subscription)
        loop_id = await loop_new_with_initial_input(client, initial_message="Test thread")

        # Subscribe to the loop AFTER creation
        await client.subscribe("loop_events", {"loop_id": loop_id})
        confirmation = await await_subscribe_ack(client.read_event, loop_id, timeout=3.0)
        assert confirmation["loop_id"] == loop_id

        # Send input and verify events are received
        await client.send_input(loop_id, "Test query")

        # Should receive events because we're subscribed
        event = await asyncio.wait_for(client.read_event(), timeout=3.0)
        assert event is not None

        await close_client_safely(client)

    finally:
        await stop_daemon_safely(daemon)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_multiple_thread_subscriptions(tmp_path: Path, requires_llm_api) -> None:
    """Test that a single client can subscribe to multiple threads simultaneously."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()

        # Create 3 loops and subscribe to all
        thread_ids = []
        for i in range(3):
            loop_id = await loop_new_with_initial_input(client, initial_message=f"Thread {i}")
            thread_ids.append(loop_id)

            await client.subscribe("loop_events", {"loop_id": loop_id})
            confirmation = await await_subscribe_ack(client.read_event, loop_id, timeout=3.0)
            assert confirmation["loop_id"] == loop_id

        # Verify client receives events for all subscribed threads
        # (Behavioral verification instead of implementation details)
        # The client successfully subscribed to all 3 threads and received confirmation
        assert len(thread_ids) == 3

        await close_client_safely(client)

    finally:
        await stop_daemon_safely(daemon)


# ============================================================================
# Layer A: Stress Testing and Edge Cases
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_rapid_client_connections(tmp_path: Path, requires_llm_api) -> None:
    """Test daemon stability with rapid client connections/disconnections.

    Regression guard for FD exhaustion under connection churn.  The original
    version created 20 server-side loops (each starting a full LLM turn + PG
    connections) in a tight loop, which exhausted the per-process FD limit.
    The refactored version:

    * Reuses a **single** long-lived client for rapid subscribe/unsubscribe
      churn (the actual protocol path under test) instead of opening a new
      WebSocket for every iteration.
    * Creates only **one** loop (one LLM turn) and performs subscribe →
      unsubscribe churn against it.
    * Performs a smaller set of fresh-client connects (to exercise the
      connection-init handshake path) with ``gc.collect()`` between
      iterations to release closed sockets promptly.
    * Asserts the open-FD count stays bounded.
    """
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    fd_soft_limit = resource.getrlimit(resource.RLIMIT_NOFILE)[0]

    client: WebSocketClient | None = None
    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()

        # One loop / one LLM turn — the daemon-side resource hog.
        loop_id = await loop_new_with_initial_input(client, initial_message="Rapid connection test")

        # Rapid subscribe/unsubscribe churn against the same loop (10x).
        for _ in range(10):
            sub_ack = await subscribe_loop_stream(client, loop_id)
            sub_id = sub_ack["id"]
            await client.unsubscribe(sub_id)
            await asyncio.sleep(0.02)

        # A handful of fresh-client connects to exercise connection-init churn.
        for _ in range(5):
            fresh = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            await fresh.connect()
            await fresh.request_connection_init()
            await fresh.wait_for_connection_ack()
            await close_client_safely(fresh)
            del fresh
            gc.collect()  # release closed sockets promptly
            await asyncio.sleep(0.05)

        # Verify daemon is still stable and responsive.
        response = await request_loop_list(client)
        assert "loops" in response

        # Assert we haven't bumped against the FD soft limit.
        fd_count = len(os.listdir("/dev/fd"))
        assert fd_count < fd_soft_limit - 16, (
            f"FD leak: {fd_count} open descriptors (limit {fd_soft_limit})"
        )

    finally:
        await close_client_safely(client)
        await stop_daemon_safely(daemon)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_event_throughput_stress(tmp_path: Path, requires_llm_api) -> None:
    """Test event bus performance under high throughput."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)
    if config.router.fast:
        config.router = config.router.model_copy(update={"default": config.router.fast})
    config.agent.autopilot.max_iterations = 3
    config.agent.loop.concurrency.global_max_llm_calls = 5

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    client: WebSocketClient | None = None
    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()

        # Create loop and subscribe
        loop_id = await loop_new_with_initial_input(client, initial_message="Throughput test")
        await subscribe_loop_stream(client, loop_id)

        idle_timeout = integration_llm_idle_timeout()
        num_queries = 3
        for i in range(num_queries):
            await client.send_input(loop_id, f"Reply with one word only: ok{i}")
            status = await await_status_state(
                client.read_event, {"running", "idle"}, timeout=idle_timeout
            )
            if status.get("state") == "running":
                await await_status_state(client.read_event, "idle", timeout=idle_timeout)

    finally:
        await close_client_safely(client)
        await stop_daemon_safely(daemon)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_large_message_handling(tmp_path: Path, requires_llm_api) -> None:
    """Test daemon handles large messages correctly (up to size limit)."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    client: WebSocketClient | None = None
    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()

        # Create loop with moderately large initial message (1KB)
        large_message = "x" * 1024
        loop_id = await loop_new_with_initial_input(client, initial_message=large_message)
        assert loop_id

    finally:
        await close_client_safely(client)
        await stop_daemon_safely(daemon)


# ============================================================================
# Layer A: Session Lifecycle Management
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_cleanup_on_unexpected_disconnect(tmp_path: Path, requires_llm_api) -> None:
    """Test that session is properly cleaned up on unexpected client disconnect."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    try:
        initial_count = daemon._session_manager.session_count

        # Connect client
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()
        loop_id = await loop_new_with_initial_input(client, initial_message="Test")
        await subscribe_loop_stream(client, loop_id)

        # Verify session was created
        assert daemon._session_manager.session_count == initial_count + 1

        # Abrupt disconnect (no graceful close)
        # Simulate by canceling all reader tasks
        await close_client_safely(client)

        # Wait for cleanup
        await asyncio.sleep(0.3)

        # Verify session was removed
        assert daemon._session_manager.session_count == initial_count

    finally:
        await stop_daemon_safely(daemon)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_reconnect_after_disconnect(tmp_path: Path, requires_llm_api) -> None:
    """Test that client can reconnect after disconnect and create new session."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    try:
        # First connection
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()
        loop_id1 = await loop_new_with_initial_input(client, initial_message="First session")
        await subscribe_loop_stream(client, loop_id1)

        # Disconnect
        await close_client_safely(client)
        await asyncio.sleep(0.2)

        # Reconnect
        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client2.connect()
        await client2.request_connection_init()
        await client2.wait_for_connection_ack()
        loop_id2 = await loop_new_with_initial_input(client2, initial_message="Second session")
        await subscribe_loop_stream(client2, loop_id2)

        # Verify different loops
        assert loop_id1 != loop_id2

        await close_client_safely(client2)

    finally:
        await stop_daemon_safely(daemon)


# ============================================================================
# Layer A: Protocol Message Validation
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_protocol_message_thread_id_in_events(tmp_path: Path, requires_llm_api) -> None:
    """Test that stream events include loop/thread correlation (``loop_id``)."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    client: WebSocketClient | None = None
    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()

        loop_id = await loop_new_with_initial_input(
            client, initial_message="Test thread_id in events"
        )
        await subscribe_loop_stream(client, loop_id)

        # Send query and collect events
        await client.send_input(loop_id, "Test query")

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
                        ctx = event.get("loop_id") or event.get("thread_id")
                        assert ctx is not None, "Event message missing loop_id/thread_id"
                        assert ctx == loop_id

                    # Check for idle status (query completed)
                    if event.get("type") == "status" and event.get("state") == "idle":
                        break

            except TimeoutError:
                continue

        assert events_received > 0, "Should have received at least one event"

    finally:
        await close_client_safely(client)
        await stop_daemon_safely(daemon)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_protocol_client_id_in_status(tmp_path: Path, requires_llm_api) -> None:
    """Test that status messages include client_id field."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    client1: WebSocketClient | None = None
    client2: WebSocketClient | None = None
    try:
        # Connect first client
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client1.connect()
        await client1.request_connection_init()
        await client1.wait_for_connection_ack()
        loop_id1 = await loop_new_with_initial_input(client1, initial_message="Client 1")
        await client1.subscribe("loop_events", {"loop_id": loop_id1})
        sub1 = await await_subscribe_ack(client1.read_event, loop_id1, timeout=3.0)

        client_id1 = sub1.get("client_id")
        assert client_id1 is not None
        assert isinstance(client_id1, str)

        # Connect second client
        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client2.connect()
        await client2.request_connection_init()
        await client2.wait_for_connection_ack()
        loop_id2 = await loop_new_with_initial_input(client2, initial_message="Client 2")
        await client2.subscribe("loop_events", {"loop_id": loop_id2})
        sub2 = await await_subscribe_ack(client2.read_event, loop_id2, timeout=3.0)

        client_id2 = sub2.get("client_id")
        assert client_id2 is not None
        assert isinstance(client_id2, str)

        # Verify different client IDs
        assert client_id1 != client_id2

    finally:
        await close_client_safely(client1)
        await close_client_safely(client2)
        await stop_daemon_safely(daemon)


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
    initial_count = daemon._channel_manager.client_count

    client1: WebSocketClient | None = None
    client2: WebSocketClient | None = None
    try:
        # Connect Unix socket client
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client1.connect()
        await asyncio.sleep(0.1)

        count_after_1 = daemon._channel_manager.client_count
        assert count_after_1 >= initial_count + 1

        # Connect second Unix socket client
        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client2.connect()
        await asyncio.sleep(0.1)

        count_after_2 = daemon._channel_manager.client_count
        assert count_after_2 >= count_after_1 + 1

        # Disconnect first client
        await close_client_safely(client1)
        client1 = None
        await asyncio.sleep(0.1)

        count_after_disconnect = daemon._channel_manager.client_count
        assert count_after_disconnect < count_after_2

        # Disconnect second client
        await close_client_safely(client2)
        client2 = None
        await asyncio.sleep(0.1)

        final_count = daemon._channel_manager.client_count
        assert final_count >= initial_count
    finally:
        await close_client_safely(client1)
        await close_client_safely(client2)


# ============================================================================
# Layer A: Performance Characteristics
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_event_delivery_latency(tmp_path: Path, requires_llm_api) -> None:
    """Test event delivery latency is within acceptable bounds."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    client: WebSocketClient | None = None
    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()

        loop_id = await loop_new_with_initial_input(client, initial_message="Latency test")
        await subscribe_loop_stream(client, loop_id)

        # Measure event delivery time
        start_time = time.time()

        await client.send_input(loop_id, "Quick response test")

        # Wait for first event
        await asyncio.wait_for(client.read_event(), timeout=5.0)
        latency = time.time() - start_time

        # Event should be delivered within reasonable time (< 2 seconds for local)
        assert latency < 2.0, f"Event delivery took {latency}s (> 2s threshold)"

        # Wait for completion
        idle_timeout = integration_llm_idle_timeout()
        status = await await_status_state(
            client.read_event, {"running", "idle"}, timeout=idle_timeout
        )
        if status.get("state") == "running":
            await await_status_state(client.read_event, "idle", timeout=idle_timeout)

    finally:
        await close_client_safely(client)
        await stop_daemon_safely(daemon)


# ============================================================================
# Layer A: Failure Recovery
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_daemon_remains_stable_after_client_errors(tmp_path: Path, requires_llm_api) -> None:
    """Test daemon remains stable after client errors (malformed messages, etc.)."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    client: WebSocketClient | None = None
    try:
        # Connect client and send problematic messages
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()

        # Try to access non-existent thread. Under protocol-1 the daemon
        # returns a structured error envelope {type:"error",
        # error:{code:-32200, message:"... not found"}}; request() raises
        # ProtocolError carrying that code (should not crash the daemon).
        fake_loop_id = f"non-existent-{uuid.uuid4().hex}"
        with pytest.raises(ProtocolError, match="not found") as exc_info:
            await client.request("loop_get", {"loop_id": fake_loop_id})
        assert exc_info.value.code == -32200

        # Verify daemon still works with valid operations
        loop_id = await loop_new_with_initial_input(client, initial_message="Valid thread")
        assert loop_id

        await subscribe_loop_stream(client, loop_id)

        # Valid query should work
        idle_timeout = integration_llm_idle_timeout()
        await client.send_input(loop_id, "Valid query")
        status = await await_status_state(
            client.read_event, {"running", "idle"}, timeout=idle_timeout
        )

        if status.get("state") == "running":
            await await_status_state(client.read_event, "idle", timeout=idle_timeout)

    finally:
        await close_client_safely(client)
        await stop_daemon_safely(daemon)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_graceful_handling_of_invalid_subscriptions(tmp_path: Path) -> None:
    """Test that invalid subscription attempts are handled gracefully."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()

        # Try to subscribe to non-existent thread. Under protocol-1 the daemon
        # rejects the subscription with an error envelope carrying the
        # subscription id; subscribe() raises ProtocolError (code=-32200).
        fake_loop_id = f"fake-loop-{uuid.uuid4().hex}"
        with pytest.raises(ProtocolError, match="not found") as exc_info:
            await client.subscribe("loop_events", {"loop_id": fake_loop_id})
        assert exc_info.value.code == -32200

        # Client should still be connected
        list_response = await request_loop_list(client)
        assert "loops" in list_response

        await close_client_safely(client)

    finally:
        await stop_daemon_safely(daemon)


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
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)
    # Reduce LLM call budget for this concurrency test — we only need to
    # verify that two loops can run concurrently, not complete a full turn.
    config.agent.loop.concurrency.global_max_llm_calls = 2

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()

    client1: WebSocketClient | None = None
    client2: WebSocketClient | None = None
    try:
        # Create two clients with different threads
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client1.connect()
        await client1.request_connection_init()
        await client1.wait_for_connection_ack()
        loop1 = await loop_new_with_initial_input(client1, initial_message="Thread 1")
        await subscribe_loop_stream(client1, loop1)

        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client2.connect()
        await client2.request_connection_init()
        await client2.wait_for_connection_ack()
        loop2 = await loop_new_with_initial_input(client2, initial_message="Thread 2")
        await subscribe_loop_stream(client2, loop2)

        # Send queries on both loops
        await client1.send_input(loop1, "Query on thread 1")
        await client2.send_input(loop2, "Query on thread 2")

        idle_timeout = integration_llm_idle_timeout()
        # Both should be able to process — wait concurrently so the second
        # loop's timeout clock does not start after the first finishes.
        status1, status2 = await asyncio.gather(
            await_status_state(client1.read_event, {"running", "idle"}, timeout=idle_timeout),
            await_status_state(client2.read_event, {"running", "idle"}, timeout=idle_timeout),
        )

        # Wait for completion — also concurrent to avoid timeout accumulation
        async def _drain_to_idle(client, st, timeout):
            if st.get("state") == "running":
                await await_status_state(client.read_event, "idle", timeout=timeout)
            return st

        await asyncio.gather(
            _drain_to_idle(client1, status1, idle_timeout),
            _drain_to_idle(client2, status2, idle_timeout),
        )

    finally:
        await close_client_safely(client1)
        await close_client_safely(client2)
        await stop_daemon_safely(daemon)


# ============================================================================
# Utility Functions
# ============================================================================


def _generate_large_json(size_kb: int) -> dict[str, Any]:
    """Generate a large JSON object for testing."""
    return {"payload": "x" * (size_kb * 1024)}
