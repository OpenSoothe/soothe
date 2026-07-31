"""WebSocket protocol integration tests for daemon backend APIs."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
import pytest_asyncio
import websockets.asyncio.client
import websockets.exceptions
from soothe.config import SootheConfig
from soothe_client import WebSocketClient

from soothe_daemon import SootheDaemon
from soothe_daemon.channels.websocket import WebSocketChannel
from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.config.models import WebSocketConfig
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    await_event_type,
    build_daemon_config,
    close_client_safely,
    force_isolated_home,
    stop_daemon_safely,
    unwrap_next,
)


def _build_daemon_config(tmp_path: Path, port: int) -> tuple[SootheConfig, SootheDaemonConfig]:
    """Build an isolated agent and daemon server config for websocket protocol tests."""
    return build_daemon_config(tmp_path=tmp_path, websocket_port=port)


@pytest_asyncio.fixture
async def websocket_daemon(tmp_path: Path):
    """Start a daemon exposing only the WebSocket transport."""
    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    config, daemon_cfg = _build_daemon_config(tmp_path, port)
    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    await asyncio.sleep(0.2)
    try:
        yield daemon, port
    finally:
        await stop_daemon_safely(daemon)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_transport_lifecycle_and_broadcast() -> None:
    """Layer A: validate channel lifecycle and broadcast fanout for WebSocket."""
    from unittest.mock import MagicMock

    port = alloc_ephemeral_port()
    config = WebSocketConfig(
        enabled=True,
        host="127.0.0.1",
        port=port,
        cors_origins=["*"],
        tls_enabled=False,
    )
    manager = MagicMock()
    channel = WebSocketChannel(config, manager=manager)
    await channel.start()
    await asyncio.sleep(0.2)

    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    try:
        await client.connect()
        await asyncio.sleep(0.1)
        assert channel.client_count == 1

        await channel.broadcast({"type": "event", "scope": "integration", "origin": "websocket"})
        event = await await_event_type(client.read_event, "event")
        assert event["type"] == "event"
    finally:
        await close_client_safely(client)
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_protocol_message_validation_returns_error() -> None:
    """Layer A: invalid protocol messages are surfaced as validation errors."""
    from unittest.mock import MagicMock

    port = alloc_ephemeral_port()
    config = WebSocketConfig(enabled=True, host="127.0.0.1", port=port, tls_enabled=False)
    manager = MagicMock()
    channel = WebSocketChannel(config, manager=manager)
    await channel.start()
    await asyncio.sleep(0.2)

    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    try:
        await client.connect()
        await asyncio.sleep(0.1)
        # Without a connection_init handshake, the channel rejects any
        # non-exempt message with a protocol-1 error envelope
        # {type:"error", error:{code:-32600, message, data?}} (RFC-450 §8.2).
        await client.send({"proto": "1", "type": "command"})
        event = await await_event_type(client.read_event, "error")
        err = event.get("error") or {}
        assert err.get("code") == -32600
        assert "Handshake" in err.get("message", "")
    finally:
        await close_client_safely(client)
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_daemon_rpc_endpoints(
    websocket_daemon: tuple[SootheDaemon, int],
) -> None:
    """Daemon RPC endpoints respond over WebSocket transport."""
    daemon, port = websocket_daemon
    _ = daemon
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    try:
        status = await client.request("daemon_status", {})
        assert status["running"] is True
        assert status["port_live"] is True
        assert isinstance(status["daemon_pid"], int)
        assert isinstance(status["started_at"], str)
        assert status["started_at"]

        providers = await client.request("config_get", {"section": "providers"})
        assert "providers" in providers
        assert isinstance(providers["providers"], (dict, list))
    finally:
        await close_client_safely(client)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_daemon_shutdown_rpc_stops_server(tmp_path: Path) -> None:
    """daemon_shutdown RPC acknowledges then stops daemon."""
    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    config, daemon_cfg = _build_daemon_config(tmp_path, port)
    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    await asyncio.sleep(0.2)

    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()
    try:
        ack = await client.request("daemon_shutdown", {})
        assert ack["status"] == "acknowledged"

        for _ in range(20):
            if not daemon._running:
                break
            await asyncio.sleep(0.1)
        assert daemon._running is False
    finally:
        await close_client_safely(client)
        await stop_daemon_safely(daemon)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_cors_rejects_disallowed_origin(tmp_path: Path) -> None:
    """Disallowed Origin header is rejected at WebSocket handshake stage."""
    from unittest.mock import MagicMock

    port = alloc_ephemeral_port()
    config = WebSocketConfig(
        enabled=True,
        host="127.0.0.1",
        port=port,
        cors_origins=["https://allowed.example"],
        tls_enabled=False,
    )
    manager = MagicMock()
    channel = WebSocketChannel(config, manager=manager)
    await channel.start()
    await asyncio.sleep(0.2)

    try:
        # The channel rejects disallowed origins at the WebSocket handshake
        # stage (Starlette returns HTTP 403 when close() is called before
        # accept()). The handshake itself raises InvalidStatus; a successful
        # connect followed by ConnectionClosed is no longer the contract.
        with pytest.raises(websockets.exceptions.InvalidStatus):
            async with websockets.asyncio.client.connect(
                f"ws://127.0.0.1:{port}",
                origin="https://evil.example",
            ):
                pass
    finally:
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_cors_accepts_allowed_origin(tmp_path: Path) -> None:
    """Allowed Origin header is accepted."""
    from unittest.mock import MagicMock

    port = alloc_ephemeral_port()
    config = WebSocketConfig(
        enabled=True,
        host="127.0.0.1",
        port=port,
        cors_origins=["https://allowed.example"],
        tls_enabled=False,
    )
    manager = MagicMock()
    channel = WebSocketChannel(config, manager=manager)
    await channel.start()
    await asyncio.sleep(0.2)

    try:
        async with websockets.asyncio.client.connect(
            f"ws://127.0.0.1:{port}",
            origin="https://allowed.example",
        ):
            assert channel.client_count == 1
    finally:
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_internal_heartbeat_not_broadcast_while_query_running(
    websocket_daemon: tuple[SootheDaemon, int],
) -> None:
    """Internal catalog events must not be broadcast to WebSocket clients (IG-435)."""
    daemon, port = websocket_daemon
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    hold_task: asyncio.Task[None] | None = None
    try:
        created = await client.request("loop_new", {})
        loop_id = created["loop_id"]
        daemon._runner.set_current_thread_id(loop_id)
        hold = asyncio.Event()
        hold_task = asyncio.create_task(hold.wait())
        daemon._active_threads = {"thread-heartbeat": hold_task}
        await client.subscribe("loop_events", {"loop_id": loop_id})

        try:
            async with asyncio.timeout(3.0):
                while True:
                    event = await client.read_event()
                    if event is None:
                        continue
                    # Protocol-1 wraps streamed events in ``next`` envelopes;
                    # unwrap to the inner ``data`` frame (legacy ``type:"event"``).
                    frame = unwrap_next(event)
                    if not isinstance(frame, dict) or frame.get("type") != "event":
                        continue
                    data = frame.get("data")
                    if isinstance(data, dict) and str(data.get("type", "")).startswith(
                        "soothe.internal."
                    ):
                        pytest.fail(
                            f"internal catalog event must not reach clients: {data.get('type')}"
                        )
        except TimeoutError:
            pass
    finally:
        if hold_task is not None:
            hold_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await hold_task
        daemon._active_threads.clear()
        await close_client_safely(client)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.xfail(
    reason="Contract expectation: explicit auth response handling is not fully implemented."
)
async def test_websocket_auth_message_should_return_auth_response() -> None:
    """Layer B: auth message contract expects an explicit auth response."""
    from unittest.mock import MagicMock

    port = alloc_ephemeral_port()
    config = WebSocketConfig(enabled=True, host="127.0.0.1", port=port, tls_enabled=False)
    manager = MagicMock()
    channel = WebSocketChannel(config, manager=manager)
    await channel.start()
    await asyncio.sleep(0.2)

    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    try:
        await client.connect()
        await client.send(
            {
                "type": "auth",
                "token": "integration-token",
                "requested_permissions": ["read", "write"],
            }
        )
        event = await await_event_type(client.read_event, "auth_response")
        assert event["success"] is True
    finally:
        await close_client_safely(client)
        await channel.stop()
