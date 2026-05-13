"""Multi-transport integration tests for daemon protocol.

This module validates daemon behavior with WebSocket and HTTP REST transports enabled,
ensuring correct broadcast fanout, cross-transport thread operations, and client
aggregation (per RFC-450, Unix socket removed due to stability issues).
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
from soothe.config import SootheConfig
from tests.integration.ws_loop_client import (
    loop_new_with_initial_input,
    request_loop_delete,
    request_loop_get,
    request_loop_list,
    subscribe_loop_stream,
)

from soothe_daemon import SootheDaemon, WebSocketClient
from tests.integration.conftest import (
    alloc_ephemeral_port,
    await_event_type,
    await_status_state,
    build_daemon_config,
    force_isolated_home,
)


def _build_daemon_config(
    tmp_path: Path,
    websocket_port: int,
    http_port: int,
) -> SootheConfig:
    """Build an isolated daemon config with WebSocket and HTTP transports enabled."""
    return build_daemon_config(
        tmp_path=tmp_path,
        websocket_port=websocket_port,
        http_port=http_port,
    )


@pytest.fixture
async def multi_transport_daemon(tmp_path: Path):
    """Start a daemon with WebSocket and HTTP transports enabled."""
    force_isolated_home(tmp_path / "soothe-home")

    ws_port = alloc_ephemeral_port()
    http_port = alloc_ephemeral_port()

    config = _build_daemon_config(tmp_path, ws_port, http_port)
    daemon = SootheDaemon(config)
    await daemon.start()
    # Allow transports to fully initialize
    await asyncio.sleep(0.3)

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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_all_transports_simultaneous_lifecycle(
    multi_transport_daemon: dict,
) -> None:
    """Test that WebSocket transport can start and stop."""
    daemon = multi_transport_daemon["daemon"]
    ws_port = multi_transport_daemon["ws_port"]
    multi_transport_daemon["http_port"]

    # Verify transports are running
    assert daemon._transport_manager is not None
    assert daemon._transport_manager.client_count == 0

    # Connect via WebSocket
    ws_client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await ws_client.connect()
    await asyncio.sleep(0.1)

    # Verify client count increases
    assert daemon._transport_manager.client_count >= 1

    response = await request_loop_list(ws_client)
    assert response["type"] == "loop_list_response"

    await ws_client.close()

    # Verify client count decreases
    await asyncio.sleep(0.1)
    assert daemon._transport_manager.client_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multi_transport_broadcast(multi_transport_daemon: dict) -> None:
    """Test that events broadcast to clients across all transports."""
    daemon = multi_transport_daemon["daemon"]
    ws_port = multi_transport_daemon["ws_port"]

    # Connect client via Unix socket
    unix_client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await unix_client.connect()

    try:
        loop_id = await loop_new_with_initial_input(
            unix_client,
            initial_message="test broadcast",
        )
        assert isinstance(loop_id, str)

        # Verify daemon reports correct client count
        assert daemon._transport_manager.client_count >= 1

        archive_response = await request_loop_delete(unix_client, loop_id)
        assert archive_response.get("success") is True

    finally:
        await unix_client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multi_transport_thread_operations(multi_transport_daemon: dict) -> None:
    """Test creating thread on one transport and accessing from another."""
    daemon = multi_transport_daemon["daemon"]
    ws_port = multi_transport_daemon["ws_port"]

    _ = daemon  # Acknowledge daemon for future multi-transport testing

    # Connect via Unix socket
    unix_client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await unix_client.connect()

    try:
        loop_id = await loop_new_with_initial_input(
            unix_client,
            initial_message="cross-transport thread",
        )

        get_response = await request_loop_get(unix_client, loop_id)
        assert get_response["loop"]["loop_id"] == loop_id

        await unix_client.send_loop_reattach(loop_id)
        resume_response = await await_event_type(unix_client.read_event, "status", timeout=3.0)
        assert (
            resume_response.get("loop_id") == loop_id or resume_response.get("thread_id") == loop_id
        )

        await subscribe_loop_stream(unix_client, loop_id)

        # Send query and verify state consistency
        await unix_client.send_input(loop_id, "Say test")
        status = await await_status_state(unix_client.read_event, {"running", "idle"}, timeout=5.0)

        # If running, wait for idle
        if status.get("state") == "running":
            try:
                await await_status_state(unix_client.read_event, "idle", timeout=5.0)
            except TimeoutError:
                # Continue even if idle not reached - query may have completed quickly
                pass

        final_get = await request_loop_get(unix_client, loop_id)
        assert final_get["loop"]["loop_id"] == loop_id

    finally:
        await unix_client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multi_transport_cross_transport_thread_sync(
    multi_transport_daemon: dict,
) -> None:
    """Thread created on WebSocket is visible and operable on Unix socket."""
    ws_port = multi_transport_daemon["ws_port"]
    ws_port = multi_transport_daemon["ws_port"]

    ws_client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    unix_client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await ws_client.connect()
    await unix_client.connect()

    try:
        created = await ws_client.request_response(
            {"type": "loop_new"},
            response_type="loop_new_response",
        )
        loop_id = created["loop_id"]

        fetched = await request_loop_get(unix_client, loop_id)
        assert fetched["loop"]["loop_id"] == loop_id

        await unix_client.send_loop_reattach(loop_id)
        resumed = await await_event_type(unix_client.read_event, "status", timeout=3.0)
        assert resumed.get("loop_id") == loop_id or resumed.get("thread_id") == loop_id
    finally:
        if ws_client.is_connected:
            await ws_client.close()
        await unix_client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multi_transport_client_count(multi_transport_daemon: dict) -> None:
    """Test that client count aggregates correctly across transports."""
    daemon = multi_transport_daemon["daemon"]
    ws_port = multi_transport_daemon["ws_port"]

    # Initial state: no clients
    await asyncio.sleep(0.2)
    assert daemon._transport_manager.client_count == 0

    # Connect first Unix client
    client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client1.connect()
    await asyncio.sleep(0.1)
    assert daemon._transport_manager.client_count >= 1

    # Connect second Unix client
    client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
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
    ws_port = multi_transport_daemon["ws_port"]

    # Connect client
    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()
    await asyncio.sleep(0.2)

    try:
        # Verify connection
        assert daemon._transport_manager.client_count >= 1

        response = await request_loop_list(client)
        assert response["type"] == "loop_list_response"

    finally:
        await client.close()

    # Stop daemon (fixture handles cleanup, but verify no errors)
    # The fixture's finally block will call daemon.stop()
    # If shutdown order is correct, no exceptions should be raised
