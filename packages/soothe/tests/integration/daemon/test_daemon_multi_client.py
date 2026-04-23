"""Integration tests for multi-client daemon with event bus architecture (RFC-0013)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from soothe.config import SootheConfig
from soothe.daemon import SootheDaemon, WebSocketClient
from tests.integration.conftest import (
    alloc_ephemeral_port,
    force_isolated_home,
)


def _build_daemon_config(tmp_path: Path, ws_port: int) -> SootheConfig:
    """Build daemon config for testing.

    Args:
        tmp_path: Temporary directory for test isolation
        ws_port: WebSocket port for daemon

    Returns:
        Configured SootheConfig instance
    """
    config = SootheConfig()
    config.daemon.transports.websocket.enabled = True
    config.daemon.transports.websocket.port = ws_port
    config.daemon.transports.unix_socket.enabled = False
    config.daemon.transports.http_rest.enabled = False
    return config


@pytest.mark.asyncio
@pytest.mark.integration
async def test_two_clients_isolated(tmp_path: Path):
    """Test that two clients don't receive each other's events."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = _build_daemon_config(tmp_path, ws_port)

    daemon = SootheDaemon(config, handle_sigint_shutdown=False)
    await daemon.start()

    try:
        # Client 1 creates thread and subscribes
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client1.connect()
        await client1.send_new_thread()
        status1 = await client1.read_event()
        assert status1 is not None
        assert status1.get("type") == "status"
        thread1 = status1.get("thread_id")
        assert thread1 is not None

        await client1.subscribe_thread(thread1)
        await client1.wait_for_subscription_confirmed(thread1)

        # Client 2 creates different thread and subscribes
        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client2.connect()
        await client2.send_new_thread()
        status2 = await client2.read_event()
        assert status2 is not None
        assert status2.get("type") == "status"
        thread2 = status2.get("thread_id")
        assert thread2 is not None
        assert thread2 != thread1

        await client2.subscribe_thread(thread2)
        await client2.wait_for_subscription_confirmed(thread2)

        # Client 1 sends input
        await client1.send_input("Test query from client 1")

        # Client 1 should receive events
        event = await asyncio.wait_for(client1.read_event(), timeout=2.0)
        assert event is not None
        assert event.get("type") in ("status", "event")

        # Client 2 should NOT receive events from client 1's thread
        with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
            await asyncio.wait_for(client2.read_event(), timeout=0.5)

        await client1.close()
        await client2.close()
    finally:
        await daemon.stop()


@pytest.mark.integration
async def test_unsubscribed_client_receives_nothing(tmp_path: Path):
    """Test that client without subscription receives no events."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = _build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, handle_sigint_shutdown=False)
    await daemon.start()

    try:
        # Client connects but doesn't subscribe
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.send_new_thread()
        status = await client.read_event()
        assert status is not None

        # Another client runs a query with subscription
        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client2.connect()
        await client2.send_new_thread()
        status2 = await client2.read_event()
        thread2 = status2.get("thread_id")
        assert thread2 is not None

        await client2.subscribe_thread(thread2)
        await client2.wait_for_subscription_confirmed(thread2)
        await client2.send_input("Test query")

        # First client should receive nothing (not subscribed)
        with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
            await asyncio.wait_for(client.read_event(), timeout=1.0)

        await client.close()
        await client2.close()
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_receives_subscription_confirmed(tmp_path: Path):
    """Test that client receives subscription confirmation."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = _build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, handle_sigint_shutdown=False)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.send_new_thread()

        status = await client.read_event()
        assert status is not None
        thread_id = status.get("thread_id")
        assert thread_id is not None

        # Subscribe to thread
        await client.subscribe_thread(thread_id)

        # Should receive confirmation
        await client.wait_for_subscription_confirmed(thread_id, timeout=2.0)

        await client.close()
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_id_in_status(tmp_path: Path):
    """Test that status message includes client_id."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = _build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, handle_sigint_shutdown=False)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.send_new_thread()

        status = await client.read_event()
        assert status is not None
        assert status.get("type") == "status"

        client_id = status.get("client_id")
        assert client_id is not None
        assert isinstance(client_id, str)

        await client.close()
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_event_message_includes_thread_id(tmp_path: Path):
    """Test that event messages include thread_id."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = _build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, handle_sigint_shutdown=False)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.send_new_thread()

        status = await client.read_event()
        thread_id = status.get("thread_id")
        assert thread_id is not None

        await client.subscribe_thread(thread_id)
        await client.wait_for_subscription_confirmed(thread_id)

        # Send a simple query
        await client.send_input("hello")

        # Read events until we get a non-status event
        for _ in range(10):
            event = await asyncio.wait_for(client.read_event(), timeout=2.0)
            if event and event.get("type") == "event":
                # Event should include thread_id
                assert "thread_id" in event
                assert event.get("thread_id") == thread_id
                break

        await client.close()
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multiple_subscriptions_same_client(tmp_path: Path):
    """Test that a client can subscribe to multiple threads."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = _build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, handle_sigint_shutdown=False)
    await daemon.start()

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")

        # Create and subscribe to thread 1
        await client.connect()
        await client.send_new_thread()
        status1 = await client.read_event()
        thread1 = status1.get("thread_id")

        await client.subscribe_thread(thread1)
        await client.wait_for_subscription_confirmed(thread1)

        # Create and subscribe to thread 2
        await client.send_new_thread()
        status2 = await client.read_event()
        thread2 = status2.get("thread_id")

        await client.subscribe_thread(thread2)
        await client.wait_for_subscription_confirmed(thread2)

        assert thread1 != thread2

        await client.close()
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_cleanup_on_disconnect(tmp_path: Path):
    """Test that session is cleaned up when client disconnects."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = _build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, handle_sigint_shutdown=False)
    await daemon.start()

    try:
        initial_session_count = daemon._session_manager.session_count

        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.send_new_thread()
        status = await client.read_event()
        thread_id = status.get("thread_id")

        await client.subscribe_thread(thread_id)
        await client.wait_for_subscription_confirmed(thread_id)

        # Session should be created
        assert daemon._session_manager.session_count == initial_session_count + 1

        # Disconnect
        await client.close()
        await asyncio.sleep(0.2)  # Give time for cleanup

        # Session should be removed
        assert daemon._session_manager.session_count == initial_session_count
    finally:
        await daemon.stop()
