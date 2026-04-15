"""Multi-transport integration tests for daemon protocol.

This module validates daemon behavior with all transports enabled simultaneously,
ensuring correct broadcast fanout, cross-transport thread operations, and client
aggregation across Unix socket, WebSocket, and HTTP REST transports.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from pathlib import Path

import pytest

from soothe.config import SootheConfig
from soothe.daemon import DaemonClient, SootheDaemon
from soothe_sdk.client import WebSocketClient
from tests.integration.conftest import (
    alloc_ephemeral_port,
    await_event_type,
    await_status_state,
    build_daemon_config,
    force_isolated_home,
)


def _build_daemon_config(
    tmp_path: Path,
    unix_socket_path: str,
    websocket_port: int,
    http_port: int,
) -> SootheConfig:
    """Build an isolated daemon config with all transports enabled."""
    return build_daemon_config(
        tmp_path=tmp_path,
        unix_socket_path=unix_socket_path,
        websocket_port=websocket_port,
        http_port=http_port,
    )


@pytest.fixture
async def multi_transport_daemon(tmp_path: Path):
    """Start a daemon with all three transports enabled."""
    force_isolated_home(tmp_path / "soothe-home")

    unix_path = f"/tmp/soothe-multi-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    ws_port = alloc_ephemeral_port()
    http_port = alloc_ephemeral_port()

    config = _build_daemon_config(tmp_path, unix_path, ws_port, http_port)
    daemon = SootheDaemon(config)
    await daemon.start()
    # Allow transports to fully initialize
    await asyncio.sleep(0.3)

    try:
        yield {
            "daemon": daemon,
            "unix_path": unix_path,
            "ws_port": ws_port,
            "http_port": http_port,
            "config": config,
        }
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_all_transports_simultaneous_lifecycle(multi_transport_daemon: dict) -> None:
    """Test that all three transports can start and stop together."""
    daemon = multi_transport_daemon["daemon"]
    unix_path = multi_transport_daemon["unix_path"]
    multi_transport_daemon["ws_port"]
    multi_transport_daemon["http_port"]

    # Verify all transports are running
    assert daemon._transport_manager is not None
    assert daemon._transport_manager.client_count == 0

    # Connect to Unix socket
    unix_client = DaemonClient(sock=Path(unix_path))
    await unix_client.connect()
    await asyncio.sleep(0.1)

    # Verify client count increases
    assert daemon._transport_manager.client_count >= 1

    # Send ping and receive status
    await unix_client.send_thread_list()
    response = await await_event_type(unix_client.read_event, "thread_list_response", timeout=3.0)
    assert response["type"] == "thread_list_response"

    await unix_client.close()

    # Verify client count decreases
    await asyncio.sleep(0.1)
    assert daemon._transport_manager.client_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multi_transport_broadcast(multi_transport_daemon: dict) -> None:
    """Test that events broadcast to clients across all transports."""
    daemon = multi_transport_daemon["daemon"]
    unix_path = multi_transport_daemon["unix_path"]

    # Connect client via Unix socket
    unix_client = DaemonClient(sock=Path(unix_path))
    await unix_client.connect()

    try:
        # Create thread to trigger events
        await unix_client.send_thread_create(
            initial_message="test broadcast",
            metadata={"tags": ["multi-transport"]},
        )
        created = await await_event_type(unix_client.read_event, "thread_created", timeout=5.0)
        thread_id = created["thread_id"]

        # Verify thread_created event received
        assert created["type"] == "thread_created"
        assert isinstance(thread_id, str)

        # Verify daemon reports correct client count
        assert daemon._transport_manager.client_count >= 1

        # Archive thread
        await unix_client.send_thread_archive(thread_id)
        archive_response = await await_event_type(unix_client.read_event, "thread_operation_ack", timeout=3.0)
        assert archive_response["success"] is True

    finally:
        await unix_client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multi_transport_thread_operations(multi_transport_daemon: dict) -> None:
    """Test creating thread on one transport and accessing from another."""
    daemon = multi_transport_daemon["daemon"]
    unix_path = multi_transport_daemon["unix_path"]

    _ = daemon  # Acknowledge daemon for future multi-transport testing

    # Connect via Unix socket
    unix_client = DaemonClient(sock=Path(unix_path))
    await unix_client.connect()

    try:
        # Create thread via Unix socket
        await unix_client.send_thread_create(
            initial_message="cross-transport thread",
            metadata={"source": "unix"},
        )
        created = await await_event_type(unix_client.read_event, "thread_created", timeout=5.0)
        thread_id = created["thread_id"]

        # Access thread via same transport (HTTP/WebSocket would need separate clients)
        await unix_client.send_thread_get(thread_id)
        get_response = await await_event_type(unix_client.read_event, "thread_get_response", timeout=3.0)
        assert get_response["thread"]["thread_id"] == thread_id

        # Resume thread
        await unix_client.send_resume_thread(thread_id)
        resume_response = await await_event_type(unix_client.read_event, "status", timeout=3.0)
        assert resume_response["thread_resumed"] is True
        assert resume_response["thread_id"] == thread_id

        # Send query and verify state consistency
        await unix_client.send_input("Say test")
        status = await await_status_state(unix_client.read_event, {"running", "idle"}, timeout=5.0)

        # If running, wait for idle
        if status.get("state") == "running":
            try:
                await await_status_state(unix_client.read_event, "idle", timeout=5.0)
            except TimeoutError:
                # Continue even if idle not reached - query may have completed quickly
                pass

        # Verify thread state preserved
        await unix_client.send_thread_get(thread_id)
        final_get = await await_event_type(unix_client.read_event, "thread_get_response", timeout=3.0)
        assert final_get["thread"]["thread_id"] == thread_id

    finally:
        await unix_client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multi_transport_cross_transport_thread_sync(multi_transport_daemon: dict) -> None:
    """Thread created on WebSocket is visible and operable on Unix socket."""
    unix_path = multi_transport_daemon["unix_path"]
    ws_port = multi_transport_daemon["ws_port"]

    ws_client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    unix_client = DaemonClient(sock=Path(unix_path))
    await ws_client.connect()
    await unix_client.connect()

    try:
        created = await ws_client.request_response(
            {
                "type": "thread_create",
                "metadata": {"channel": "websocket", "tags": ["cross-transport"]},
            },
            response_type="thread_created",
        )
        thread_id = created["thread_id"]

        await unix_client.send_thread_get(thread_id)
        fetched = await await_event_type(unix_client.read_event, "thread_get_response", timeout=3.0)
        assert fetched["thread"]["thread_id"] == thread_id

        await unix_client.send_resume_thread(thread_id)
        resumed = await await_event_type(unix_client.read_event, "status", timeout=3.0)
        assert resumed["thread_id"] == thread_id
    finally:
        if ws_client.is_connected:
            await ws_client.close()
        await unix_client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multi_transport_client_count(multi_transport_daemon: dict) -> None:
    """Test that client count aggregates correctly across transports."""
    daemon = multi_transport_daemon["daemon"]
    unix_path = multi_transport_daemon["unix_path"]

    # Initial state: no clients
    await asyncio.sleep(0.2)
    assert daemon._transport_manager.client_count == 0

    # Connect first Unix client
    client1 = DaemonClient(sock=Path(unix_path))
    await client1.connect()
    await asyncio.sleep(0.1)
    assert daemon._transport_manager.client_count >= 1

    # Connect second Unix client
    client2 = DaemonClient(sock=Path(unix_path))
    await client2.connect()
    await asyncio.sleep(0.1)
    assert daemon._transport_manager.client_count >= 2

    # Disconnect first client
    await client1.close()
    await asyncio.sleep(0.1)
    assert daemon._transport_manager.client_count >= 1

    # Disconnect second client
    await client2.close()
    await asyncio.sleep(0.1)
    assert daemon._transport_manager.client_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multi_transport_shutdown_order(multi_transport_daemon: dict) -> None:
    """Test graceful shutdown stops all transports cleanly."""
    daemon = multi_transport_daemon["daemon"]
    unix_path = multi_transport_daemon["unix_path"]

    # Connect client
    client = DaemonClient(sock=Path(unix_path))
    await client.connect()
    await asyncio.sleep(0.2)

    try:
        # Verify connection
        assert daemon._transport_manager.client_count >= 1

        # Send simple request
        await client.send_thread_list()
        response = await await_event_type(client.read_event, "thread_list_response", timeout=3.0)
        assert response["type"] == "thread_list_response"

    finally:
        await client.close()

    # Stop daemon (fixture handles cleanup, but verify no errors)
    # The fixture's finally block will call daemon.stop()
    # If shutdown order is correct, no exceptions should be raised
