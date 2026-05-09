"""WebSocket protocol integration tests for daemon backend APIs."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
import pytest_asyncio
import websockets.asyncio.client
import websockets.exceptions
from soothe_sdk.client import WebSocketClient

from soothe.config import SootheConfig
from soothe.config.daemon_config import WebSocketConfig
from soothe.daemon import SootheDaemon
from soothe.daemon.transports.websocket import WebSocketTransport
from tests.integration.conftest import (
    alloc_ephemeral_port,
    await_event_type,
    force_isolated_home,
    get_base_config,
)


def _build_daemon_config(tmp_path: Path, port: int) -> SootheConfig:
    """Build an isolated daemon config for websocket protocol tests."""
    base_config = get_base_config()

    return SootheConfig(
        providers=base_config.providers,
        router=base_config.router,
        vector_stores=base_config.vector_stores,
        vector_store_router=base_config.vector_store_router,
        workspace_dir=str(tmp_path / "workspace"),
        persistence={"persist_dir": str(tmp_path / "persistence")},
        protocols={
            "memory": {"enabled": False},
            "durability": {
                "backend": "sqlite",
                "persist_dir": str(tmp_path / "durability"),
            },
        },
        daemon={
            "transports": {
                "websocket": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": port,
                    "cors_origins": ["*"],
                    "tls_enabled": False,
                },
                "http_rest": {"enabled": False},
            },
        },
    )


@pytest_asyncio.fixture
async def websocket_daemon(tmp_path: Path):
    """Start a daemon exposing only the WebSocket transport."""
    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    config = _build_daemon_config(tmp_path, port)
    daemon = SootheDaemon(config)
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
    await transport.start(lambda msg: None)
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
    await transport.start(lambda msg: None)
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
    config = _build_daemon_config(tmp_path, port)
    daemon = SootheDaemon(config)
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
        async with websockets.asyncio.client.connect(
            f"ws://127.0.0.1:{port}",
            origin="https://evil.example",
        ) as denied:
            with pytest.raises(websockets.exceptions.ConnectionClosed):
                await denied.recv()
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
async def test_websocket_heartbeat_emits_while_query_running(
    websocket_daemon: tuple[SootheDaemon, int],
) -> None:
    """Daemon emits heartbeat events over WebSocket while query is marked running."""
    daemon, port = websocket_daemon
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    await client.wait_for_daemon_ready()

    try:
        created = await client.request_response(
            {"type": "thread_create"},
            response_type="thread_created",
        )
        thread_id = created["thread_id"]
        daemon._runner.set_current_thread_id(thread_id)
        daemon._query_running = True
        await client.subscribe_thread(thread_id)
        await client.wait_for_subscription_confirmed(thread_id, timeout=5.0)

        async with asyncio.timeout(8.0):
            while True:
                event = await client.read_event()
                if event is None or event.get("type") != "event":
                    continue
                data = event.get("data")
                if isinstance(data, dict) and data.get("type") == "soothe.system.daemon.heartbeat":
                    assert event["thread_id"] == thread_id
                    assert data["state"] == "running"
                    break
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
    await transport.start(lambda msg: None)
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
