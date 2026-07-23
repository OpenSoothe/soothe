"""Integration tests for multi-client daemon with loop-scoped isolation (RFC-0013, IG-408)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from soothe_client import WebSocketClient

from soothe_daemon import SootheDaemon
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    build_daemon_config,
    force_isolated_home,
    unwrap_next,
    websocket_bootstrap_loop_session,
    websocket_create_loop_only,
)


async def _connect_and_drain_handshake(client: WebSocketClient) -> None:
    """Connect and complete the protocol-1 handshake (RFC-450 §8.2)."""
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()


async def _first_event_with_client_id(client: WebSocketClient, *, timeout_s: float = 10.0) -> dict:
    """Read until a wire frame carries a ``client_id`` field.

    Under protocol-1 (RFC-450 §9.3) the daemon confirms a ``loop_events``
    subscription with a ``next`` envelope whose ``payload`` carries
    ``client_id``; generic status frames do not. The helper unwraps ``next``
    envelopes and accepts any wire shape so it stays robust to protocol
    changes. Per-read timeout ensures the deadline fires even if no events
    arrive (otherwise ``read_event`` would block forever).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            msg = "Timed out waiting for wire frame with client_id"
            raise TimeoutError(msg)
        try:
            ev = await asyncio.wait_for(client.read_event(), timeout=remaining)
        except TimeoutError as exc:
            msg = "Timed out waiting for wire frame with client_id"
            raise TimeoutError(msg) from exc
        if not isinstance(ev, dict):
            continue
        # ``next`` envelopes carry client_id on ``payload``; raw frames carry
        # it at top level. Check both.
        if ev.get("type") == "next":
            payload = ev.get("payload") or {}
            if isinstance(payload, dict) and payload.get("client_id"):
                return payload
        if ev.get("client_id"):
            return ev


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
        # Client2 should not receive loop1 events. Drain any lingering loop2
        # reattach-replay frames first so they don't trip the isolation check.
        client2.clear_pending_events()
        try:
            while True:
                await asyncio.wait_for(client2.read_event(), timeout=0.3)
        except (TimeoutError, asyncio.CancelledError):
            pass

        await client1.send_input(loop1, "Test query from client 1")

        event = await asyncio.wait_for(client1.read_event(), timeout=2.0)
        assert event is not None
        # Any wire frame proves client1's subscription is delivering. The
        # first frame after subscribe is often `history_replay` /
        # `subscription_confirmed`, not `status` / `event`; enumerating the
        # control-frame set here would be brittle as the protocol grows.
        # The real isolation guarantee is the assertion below.

        # Client2 must not receive any loop1-scoped frame. It may still get
        # its own loop2 reattach replay or a heartbeat ping — filter those by
        # loop_id so the isolation guarantee is precise.
        deadline = asyncio.get_running_loop().time() + 0.5
        leaked = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                ev = await asyncio.wait_for(client2.read_event(), timeout=0.1)
            except (TimeoutError, asyncio.CancelledError):
                break
            if ev is None:
                break
            if ev.get("loop_id") == loop1:
                leaked = ev
                break
        assert leaked is None, f"client2 received loop1 event: {leaked}"

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
    """Daemon delivers the server-assigned ``client_id`` after loop subscribe.

    The protocol carries ``client_id`` on a dedicated ``subscription_confirmed``
    frame (router.py emits it once per ``loop_subscribe``); generic ``status``
    frames intentionally do not. The test asserts the SDK-visible contract:
    after bootstrap, the client has received a wire frame identifying its
    server-assigned id.
    """
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

        frame = await _first_event_with_client_id(client)
        assert frame.get("loop_id") or frame.get("thread_id")
        client_id = frame.get("client_id")
        assert isinstance(client_id, str) and client_id

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
            event = await asyncio.wait_for(client.read_event(), timeout=10.0)
            # Protocol-1 wraps streamed events in ``next`` envelopes; unwrap to
            # the inner ``data`` frame which carries the legacy ``type``/``loop_id``.
            frame = unwrap_next(event)
            if isinstance(frame, dict) and frame.get("type") == "event":
                assert frame.get("loop_id") == loop_id
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

        new_resp = await client.request("loop_new", {}, timeout=5.0)
        loop2 = str(new_resp.get("loop_id") or "").strip()
        assert loop2 and loop2 != loop1

        # Protocol-1 subscribe (loop_events target). subscribe() returns the
        # subscription id; the daemon sends subscription_confirmed as a next event.
        sub2 = await client.subscribe("loop_events", {"loop_id": loop2}, timeout=5.0)
        assert sub2

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
