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
    await_status_state,
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
        persistence={"persist_dir": str(tmp_path / "persistence")},
        protocols={
            "memory": {"enabled": False},
            "durability": {
                "backend": "json",
                "persist_dir": str(tmp_path / "durability"),
            },
        },
        daemon={
            "transports": {
                "unix_socket": {"enabled": False},
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
        performance={"unified_classification": False},
    )


@pytest_asyncio.fixture
async def websocket_daemon(tmp_path: Path):
    """Start a daemon exposing only the WebSocket transport."""
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
async def test_websocket_protocol_thread_backend_operations(
    websocket_daemon: tuple[SootheDaemon, int],
) -> None:
    """Layer A: validate thread protocol operations over WebSocket client."""
    daemon, port = websocket_daemon
    _ = daemon
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()

    try:
        await client.send(
            {
                "type": "thread_create",
                "metadata": {
                    "channel": "websocket",
                    "tags": ["websocket"],
                    "priority": "normal",
                },
            }
        )
        created = await await_event_type(client.read_event, "thread_created")
        thread_id = created["thread_id"]
        assert isinstance(thread_id, str)

        await client.send({"type": "thread_list", "include_stats": True})
        full_list_response = await await_event_type(client.read_event, "thread_list_response")
        assert full_list_response["total"] >= 1
        assert any(entry["thread_id"] == thread_id for entry in full_list_response["threads"])

        await client.send(
            {
                "type": "thread_list",
                "filter": {
                    "status": "idle",
                    "tags": ["websocket"],
                    "priority": "normal",
                },
                "include_stats": True,
            }
        )
        filtered_response = await await_event_type(client.read_event, "thread_list_response")
        assert any(entry["thread_id"] == thread_id for entry in filtered_response["threads"])
        filtered_entry = next(
            entry for entry in filtered_response["threads"] if entry["thread_id"] == thread_id
        )
        assert "websocket" in filtered_entry["metadata"].get("tags", [])

        await client.send({"type": "thread_get", "thread_id": thread_id})
        thread_get = await await_event_type(client.read_event, "thread_get_response")
        assert thread_get["thread"]["thread_id"] == thread_id

        await client.send({"type": "resume_thread", "thread_id": thread_id})
        resume_response = await await_event_type(client.read_event, "status")
        assert resume_response["thread_resumed"] is True
        assert resume_response["thread_id"] == thread_id

        await client.send({"type": "input", "text": "Say hello"})
        first_turn_status = await await_status_state(
            client.read_event,
            {"running", "idle"},
            timeout=8.0,
        )
        if first_turn_status.get("state") == "running":
            await await_status_state(client.read_event, "idle", timeout=8.0)

        # Verify second input works (proves first completed successfully)
        await client.send({"type": "input", "text": "Say world"})
        second_turn_status = await await_status_state(
            client.read_event,
            {"running", "idle"},
            timeout=8.0,
        )
        if second_turn_status.get("state") == "running":
            await await_status_state(client.read_event, "idle", timeout=8.0)

        # Verify thread operations work after multiple turns
        await client.send(
            {"type": "thread_messages", "thread_id": thread_id, "limit": 5, "offset": 0}
        )
        messages = await await_event_type(
            client.read_event, "thread_messages_response", timeout=5.0
        )
        assert messages["thread_id"] == thread_id
        assert isinstance(messages["messages"], list)

        await client.send(
            {"type": "thread_messages", "thread_id": thread_id, "limit": 5, "offset": 0}
        )
        messages = await await_event_type(client.read_event, "thread_messages_response")
        assert messages["thread_id"] == thread_id
        assert isinstance(messages["messages"], list)

        await client.send(
            {
                "type": "thread_list",
                "filter": {"priority": "normal"},
                "include_stats": True,
            }
        )
        list_after_turns = await await_event_type(
            client.read_event, "thread_list_response", timeout=3.0
        )
        assert any(item["thread_id"] == thread_id for item in list_after_turns["threads"])

        await client.send({"type": "thread_artifacts", "thread_id": thread_id})
        artifacts = await await_event_type(
            client.read_event, "thread_artifacts_response", timeout=3.0
        )
        assert artifacts["thread_id"] == thread_id

        await client.send({"type": "thread_archive", "thread_id": thread_id})
        archive = await await_event_type(client.read_event, "thread_operation_ack")
        assert archive["operation"] == "archive"
        assert archive["thread_id"] == thread_id
        assert archive["success"] is True

        await client.send({"type": "thread_delete", "thread_id": thread_id})
        delete_response = await await_event_type(client.read_event, "thread_operation_ack")
        assert delete_response["operation"] == "delete"
        assert delete_response["thread_id"] == thread_id
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_protocol_thread_state_round_trip(
    websocket_daemon: tuple[SootheDaemon, int],
) -> None:
    """Thread state can be updated and fetched through client-scoped RPCs."""
    daemon, port = websocket_daemon
    _ = daemon
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()

    try:
        await client.send({"type": "thread_create"})
        created = await await_event_type(client.read_event, "thread_created")
        thread_id = created["thread_id"]

        update_response = await client.request_response(
            {
                "type": "thread_update_state",
                "thread_id": thread_id,
                "values": {"_context_tokens": 123},
            },
            response_type="thread_update_state_response",
        )
        assert update_response["thread_id"] == thread_id
        assert update_response["success"] is True

        state_response = await client.request_response(
            {"type": "thread_state", "thread_id": thread_id},
            response_type="thread_state_response",
        )
        assert state_response["thread_id"] == thread_id
        assert state_response["values"]["_context_tokens"] == 123
    finally:
        if client.is_connected:
            await client.close()


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
        assert isinstance(providers["providers"], dict)
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_daemon_shutdown_rpc_stops_server(tmp_path: Path) -> None:
    """daemon_shutdown RPC acknowledges then stops daemon."""
    port = alloc_ephemeral_port()
    config = _build_daemon_config(tmp_path, port)
    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.2)

    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
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
        if daemon._running:
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
