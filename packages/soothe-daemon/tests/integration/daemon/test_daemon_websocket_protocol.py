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
from soothe_sdk.client import WebSocketClient

from soothe_daemon import SootheDaemon
from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.config.models import WebSocketConfig
from soothe_daemon.transports.websocket import WebSocketTransport

from ..daemon_fixtures import (
    alloc_ephemeral_port,
    await_event_type,
    build_daemon_config,
    force_isolated_home,
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
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_transport_lifecycle_and_broadcast() -> None:
    """Layer A: validate transport lifecycle and broadcast fanout for WebSocket."""
    port = alloc_ephemeral_port()
    config = WebSocketConfig(
        enabled=True,
        host="127.0.0.1",
        port=port,
        cors_origins=["*"],
        tls_enabled=False,
    )
    transport = WebSocketTransport(config)
    await transport.start(lambda _client_id, _msg: None)
    await asyncio.sleep(0.2)

    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    try:
        await client.connect()
        await asyncio.sleep(0.1)
        assert transport.client_count == 1

        await transport.broadcast({"type": "event", "scope": "integration", "origin": "websocket"})
        event = await await_event_type(client.read_event, "event")
        assert event["type"] == "event"
    finally:
        if client.is_connected:
            await client.close()
        await transport.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_protocol_message_validation_returns_error() -> None:
    """Layer A: invalid protocol messages are surfaced as validation errors."""
    port = alloc_ephemeral_port()
    config = WebSocketConfig(enabled=True, host="127.0.0.1", port=port, tls_enabled=False)
    transport = WebSocketTransport(config)
    await transport.start(lambda _client_id, _msg: None)
    await asyncio.sleep(0.2)

    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    try:
        await client.connect()
        await asyncio.sleep(0.1)
        await client.send({"type": "command"})
        event = await await_event_type(client.read_event, "error")
        assert event["code"] == "INVALID_MESSAGE"
    finally:
        if client.is_connected:
            await client.close()
        await transport.stop()


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
    await client.wait_for_daemon_ready()

    try:
        status = await client.request_response(
            {"type": "daemon_status"},
            response_type="daemon_status_response",
        )
        assert status["running"] is True
        assert status["port_live"] is True
        assert isinstance(status["daemon_pid"], int)

        providers = await client.request_response(
            {"type": "config_get", "section": "providers"},
            response_type="config_get_response",
        )
        assert "providers" in providers
        assert isinstance(providers["providers"], (dict, list))
    finally:
        if client.is_connected:
            await client.close()


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
    await client.wait_for_daemon_ready()
    try:
        ack = await client.request_response(
            {"type": "daemon_shutdown"},
            response_type="shutdown_ack",
        )
        assert ack["status"] == "acknowledged"

        for _ in range(20):
            if not daemon._running:
                break
            await asyncio.sleep(0.1)
        assert daemon._running is False
    finally:
        if client.is_connected:
            await client.close()
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_cors_rejects_disallowed_origin(tmp_path: Path) -> None:
    """Disallowed Origin header is rejected at WebSocket handshake stage."""
    port = alloc_ephemeral_port()
    config = WebSocketConfig(
        enabled=True,
        host="127.0.0.1",
        port=port,
        cors_origins=["https://allowed.example"],
        tls_enabled=False,
    )
    transport = WebSocketTransport(config)
    await transport.start(lambda _client_id, _msg: None)
    await asyncio.sleep(0.2)

    try:
        # The transport rejects disallowed origins at the WebSocket handshake
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
        await transport.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_cors_accepts_allowed_origin(tmp_path: Path) -> None:
    """Allowed Origin header is accepted."""
    port = alloc_ephemeral_port()
    config = WebSocketConfig(
        enabled=True,
        host="127.0.0.1",
        port=port,
        cors_origins=["https://allowed.example"],
        tls_enabled=False,
    )
    transport = WebSocketTransport(config)
    await transport.start(lambda _client_id, _msg: None)
    await asyncio.sleep(0.2)

    try:
        async with websockets.asyncio.client.connect(
            f"ws://127.0.0.1:{port}",
            origin="https://allowed.example",
        ):
            assert transport.client_count == 1
    finally:
        await transport.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_internal_heartbeat_not_broadcast_while_query_running(
    websocket_daemon: tuple[SootheDaemon, int],
) -> None:
    """Internal catalog events must not be broadcast to WebSocket clients (IG-435)."""
    daemon, port = websocket_daemon
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    await client.wait_for_daemon_ready()

    try:
        created = await client.request_response(
            {"type": "loop_new"},
            response_type="loop_new_response",
        )
        loop_id = created["loop_id"]
        daemon._runner.set_current_thread_id(loop_id)
        daemon._query_running = True
        await client.send_loop_subscribe(loop_id)
        await await_event_type(client.read_event, "subscription_confirmed", timeout=5.0)

        try:
            async with asyncio.timeout(3.0):
                while True:
                    event = await client.read_event()
                    if event is None or event.get("type") != "event":
                        continue
                    data = event.get("data")
                    if isinstance(data, dict) and str(data.get("type", "")).startswith(
                        "soothe.internal."
                    ):
                        pytest.fail(
                            f"internal catalog event must not reach clients: {data.get('type')}"
                        )
        except TimeoutError:
            pass
    finally:
        daemon._query_running = False
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.xfail(
    reason="Contract expectation: explicit auth response handling is not fully implemented."
)
async def test_websocket_auth_message_should_return_auth_response() -> None:
    """Layer B: auth message contract expects an explicit auth response."""
    port = alloc_ephemeral_port()
    config = WebSocketConfig(enabled=True, host="127.0.0.1", port=port, tls_enabled=False)
    transport = WebSocketTransport(config)
    await transport.start(lambda _client_id, _msg: None)
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
        if client.is_connected:
            await client.close()
        await transport.stop()
