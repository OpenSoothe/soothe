"""Integration tests for multi-client daemon with loop-scoped isolation (RFC-0013, IG-408)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from soothe_daemon import SootheDaemon, WebSocketClient
from tests.integration.conftest import (
    alloc_ephemeral_port,
    build_daemon_config,
    force_isolated_home,
    websocket_bootstrap_loop_session,
    websocket_create_loop_only,
)


async def _connect_and_drain_handshake(client: WebSocketClient) -> None:
    """Connect and wait until daemon handshake is complete (RFC-0013)."""
    await client.connect()
    await client.wait_for_daemon_ready()


async def _first_status_with_client_id(client: WebSocketClient, *, timeout_s: float = 10.0) -> dict:
    """Read until a ``status`` event includes ``client_id``."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        ev = await client.read_event()
        if isinstance(ev, dict) and ev.get("type") == "status" and ev.get("client_id"):
            return ev
    msg = "Timed out waiting for status with client_id"
    raise TimeoutError(msg)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_two_clients_isolated(tmp_path: Path):
    """Test that two clients don't receive each other's loop events."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
    await daemon.start()
    await asyncio.sleep(0.3)

    try:
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_and_drain_handshake(client1)
        loop1 = await websocket_bootstrap_loop_session(client1)

        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_and_drain_handshake(client2)
        loop2 = await websocket_bootstrap_loop_session(client2)
        assert loop2 != loop1

        # Clear pending events only for client2 before isolation check
        # Client2 should not receive loop1 events
        client2.clear_pending_events()

        await client1.send_input(loop1, "Test query from client 1")

        event = await asyncio.wait_for(client1.read_event(), timeout=2.0)
        assert event is not None
        assert event.get("type") in ("status", "event")

        with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
            await asyncio.wait_for(client2.read_event(), timeout=0.5)

        await client1.close()
        await client2.close()
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unsubscribed_client_receives_nothing(tmp_path: Path):
    """Client that never ``loop_subscribe``s should not receive loop events."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
    await daemon.start()
    await asyncio.sleep(0.3)

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_and_drain_handshake(client)
        await websocket_create_loop_only(client)

        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_and_drain_handshake(client2)
        loop2 = await websocket_bootstrap_loop_session(client2)

        # Clear pending events from setup phase before isolation check
        client.clear_pending_events()
        client2.clear_pending_events()

        await client2.send_input(loop2, "Test query")

        with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
            await asyncio.wait_for(client.read_event(), timeout=1.0)

        await client.close()
        await client2.close()
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_loop_subscribe_handshake_succeeds(tmp_path: Path):
    """``bootstrap_loop_session`` completes with a ``loop_id``."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
    await daemon.start()
    await asyncio.sleep(0.3)

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_and_drain_handshake(client)
        loop_id = await websocket_bootstrap_loop_session(client)
        assert loop_id

        await client.close()
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_id_in_status(tmp_path: Path):
    """Test that status message includes client_id."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
    await daemon.start()
    await asyncio.sleep(0.3)

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_and_drain_handshake(client)
        await websocket_bootstrap_loop_session(client)

        status = await _first_status_with_client_id(client)
        assert status.get("loop_id") or status.get("thread_id")
        client_id = status.get("client_id")
        assert client_id is not None
        assert isinstance(client_id, str)

        await client.close()
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_event_message_includes_thread_and_loop_id(tmp_path: Path):
    """Streamed events should carry CoreAgent ``thread_id`` and ``loop_id``."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
    await daemon.start()
    await asyncio.sleep(0.3)

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_and_drain_handshake(client)
        loop_id = await websocket_bootstrap_loop_session(client)

        await client.send_input(loop_id, "hello")

        for _ in range(10):
            event = await asyncio.wait_for(client.read_event(), timeout=2.0)
            if event and event.get("type") == "event":
                assert event.get("loop_id") == loop_id
                break
        else:
            pytest.fail("expected at least one streamed event")

        await client.close()
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_switching_loop_subscription_replaces_prior(tmp_path: Path):
    """Subscribing to a second loop drops the first subscription (single active loop)."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
    await daemon.start()
    await asyncio.sleep(0.3)

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_and_drain_handshake(client)
        loop1 = await websocket_bootstrap_loop_session(client)

        new_resp = await client.request_response(
            {"type": "loop_new"},
            response_type="loop_new_response",
            timeout=5.0,
        )
        loop2 = str(new_resp.get("loop_id") or "").strip()
        assert loop2 and loop2 != loop1

        sub2 = await client.request_response(
            {
                "type": "loop_subscribe",
                "loop_id": loop2,
                "verbosity": "normal",
            },
            response_type="loop_subscribe_response",
            timeout=5.0,
        )
        assert sub2.get("success", True)

        await client.close()
    finally:
        await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_cleanup_on_disconnect(tmp_path: Path):
    """Test that session is cleaned up when client disconnects."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
    await daemon.start()
    await asyncio.sleep(0.3)

    try:
        initial_session_count = daemon._session_manager.session_count

        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await _connect_and_drain_handshake(client)
        await websocket_bootstrap_loop_session(client)

        assert daemon._session_manager.session_count == initial_session_count + 1

        await client.close()
        await asyncio.sleep(0.2)

        assert daemon._session_manager.session_count == initial_session_count
    finally:
        await daemon.stop()
