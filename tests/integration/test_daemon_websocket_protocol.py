"""WebSocket protocol integration tests for daemon backend APIs."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
import socket
from pathlib import Path

import pytest

from soothe.config import SootheConfig
from soothe.config.daemon_config import WebSocketConfig
from soothe.daemon import SootheDaemon
from soothe.daemon.transports.websocket import WebSocketTransport
from soothe.daemon.websocket_client import WebSocketClient


def _alloc_ephemeral_port() -> int:
    """Allocate an available localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _force_isolated_home(home: Path) -> None:
    """Force daemon paths to a test-local SOOTHE_HOME to avoid pid-socket contention."""
    os.environ["SOOTHE_HOME"] = str(home)
    import soothe.config as soothe_config
    from soothe import config as config_module

    soothe_config.SOOTHE_HOME = str(home)
    config_module.SOOTHE_HOME = str(home)

    import soothe.daemon.paths as daemon_paths

    # Update in-memory constants for already-imported modules
    daemon_paths.SOOTHE_HOME = str(home)
    importlib.reload(daemon_paths)

    import soothe.daemon.thread_logger as daemon_thread_logger

    daemon_thread_logger.SOOTHE_HOME = str(home)

    import soothe.core.thread.manager as thread_manager

    thread_manager.SOOTHE_HOME = str(home)


async def _await_event_type(readable, expected_type: str, timeout: float = 2.5) -> dict:
    """Read protocol events until a specific type is observed."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            msg = f"Timed out waiting for event type: {expected_type}"
            raise TimeoutError(msg)
        event = await asyncio.wait_for(readable(), timeout=remaining)
        if event is not None and event.get("type") == expected_type:
            return event


async def _await_status_state(
    readable,
    expected_states: str | set[str] | tuple[str, ...],
    timeout: float = 3.0,
) -> dict:
    """Read websocket events until a status event with the expected state appears."""
    expected: set[str] = {expected_states} if isinstance(expected_states, str) else set(expected_states)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            states = ", ".join(sorted(expected))
            msg = f"Timed out waiting for status state: {states}"
            raise TimeoutError(msg)
        event = await asyncio.wait_for(readable(), timeout=remaining)
        if event is not None and event.get("type") == "status" and event.get("state") in expected:
            return event


def _build_daemon_config(tmp_path: Path, port: int) -> tuple[SootheConfig]:
    """Build an isolated daemon config for websocket protocol tests."""
    # Try to load from config.dev.yml to get available providers
    config_path = Path(__file__).parent.parent.parent / "config.dev.yml"
    if config_path.exists():
        base_config = SootheConfig.from_yaml_file(str(config_path))
    else:
        base_config = SootheConfig()

    return (
        SootheConfig(
            providers=base_config.providers,
            router=base_config.router,
            vector_stores=base_config.vector_stores,
            vector_store_router=base_config.vector_store_router,
            persistence={"persist_dir": str(tmp_path / "persistence")},
            protocols={
                "memory": {"enabled": False},
                "durability": {"backend": "json", "persist_dir": str(tmp_path / "durability")},
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
            # Disable unified classification for integration tests to avoid model compatibility issues
            performance={"unified_classification": False},
        ),
    )


@pytest.fixture
async def websocket_daemon(tmp_path: Path):
    """Start a daemon exposing only the WebSocket transport."""
    _force_isolated_home(tmp_path / "soothe-home")
    port = _alloc_ephemeral_port()
    (config,) = _build_daemon_config(tmp_path, port)
    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.4)
    try:
        yield daemon, port
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_transport_lifecycle_and_broadcast() -> None:
    """Layer A: validate transport lifecycle and broadcast fanout for WebSocket."""
    port = _alloc_ephemeral_port()
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
        event = await _await_event_type(client.read_event, "event")
        assert event["type"] == "event"
    finally:
        if client.is_connected:
            await client.close()
        await transport.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_protocol_message_validation_returns_error() -> None:
    """Layer A: invalid protocol messages are surfaced as validation errors."""
    port = _alloc_ephemeral_port()
    config = WebSocketConfig(enabled=True, host="127.0.0.1", port=port, tls_enabled=False)
    transport = WebSocketTransport(config)
    await transport.start(lambda msg: None)
    await asyncio.sleep(0.2)

    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    try:
        await client.connect()
        await asyncio.sleep(0.1)
        await client.send({"type": "command"})
        event = await _await_event_type(client.read_event, "error")
        assert event["code"] == "INVALID_MESSAGE"
    finally:
        if client.is_connected:
            await client.close()
        await transport.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_protocol_thread_backend_operations(websocket_daemon: tuple[SootheDaemon, int]) -> None:
    """Layer A: validate thread protocol operations over WebSocket client."""
    daemon, port = websocket_daemon
    _ = daemon
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()

    try:
        await client.send(
            {
                "type": "thread_create",
                "metadata": {"channel": "websocket", "tags": ["websocket"], "priority": "normal"},
            }
        )
        created = await _await_event_type(client.read_event, "thread_created")
        thread_id = created["thread_id"]
        assert isinstance(thread_id, str)

        await client.send({"type": "thread_list", "include_stats": True})
        full_list_response = await _await_event_type(client.read_event, "thread_list_response")
        assert full_list_response["total"] >= 1
        assert any(entry["thread_id"] == thread_id for entry in full_list_response["threads"])

        await client.send(
            {
                "type": "thread_list",
                "filter": {"status": "idle", "tags": ["websocket"], "priority": "normal"},
                "include_stats": True,
            }
        )
        filtered_response = await _await_event_type(client.read_event, "thread_list_response")
        assert any(entry["thread_id"] == thread_id for entry in filtered_response["threads"])
        filtered_entry = next(entry for entry in filtered_response["threads"] if entry["thread_id"] == thread_id)
        assert "websocket" in filtered_entry["metadata"].get("tags", [])

        await client.send({"type": "thread_get", "thread_id": thread_id})
        thread_get = await _await_event_type(client.read_event, "thread_get_response")
        assert thread_get["thread"]["thread_id"] == thread_id

        await client.send({"type": "resume_thread", "thread_id": thread_id})
        resume_response = await _await_event_type(client.read_event, "status")
        assert resume_response["thread_resumed"] is True
        assert resume_response["thread_id"] == thread_id

        await client.send({"type": "input", "text": "Begin websocket thread continuation story."})
        first_turn_status = await _await_status_state(
            client.read_event,
            {"running", "idle"},
            timeout=4.0,
        )
        if first_turn_status.get("state") == "running":
            await _await_status_state(client.read_event, "idle", timeout=4.0)

        await client.send({"type": "thread_messages", "thread_id": thread_id, "limit": 10, "offset": 0})
        first_messages = await _await_event_type(client.read_event, "thread_messages_response")
        first_user_messages = [
            message["content"] for message in first_messages["messages"] if message.get("role") == "user"
        ]
        assert "Begin websocket thread continuation story." in first_user_messages

        await client.send({"type": "input", "text": "Continue websocket thread using prior history."})
        second_turn_status = await _await_status_state(
            client.read_event,
            {"running", "idle"},
            timeout=4.0,
        )
        if second_turn_status.get("state") == "running":
            await _await_status_state(client.read_event, "idle", timeout=4.0)

        await client.send({"type": "thread_messages", "thread_id": thread_id, "limit": 10, "offset": 0})
        second_messages = await _await_event_type(client.read_event, "thread_messages_response")
        second_user_messages = [
            message["content"] for message in second_messages["messages"] if message.get("role") == "user"
        ]
        assert len(second_user_messages) >= 2
        assert "Begin websocket thread continuation story." in second_user_messages
        assert "Continue websocket thread using prior history." in second_user_messages

        await client.send({"type": "thread_list", "filter": {"priority": "normal"}, "include_stats": True})
        list_after_turns = await _await_event_type(client.read_event, "thread_list_response")
        listed_thread = next(item for item in list_after_turns["threads"] if item["thread_id"] == thread_id)
        assert listed_thread.get("last_human_message") is not None

        await client.send({"type": "thread_messages", "thread_id": thread_id, "limit": 5, "offset": 0})
        messages = await _await_event_type(client.read_event, "thread_messages_response")
        assert messages["thread_id"] == thread_id
        assert isinstance(messages["messages"], list)

        await client.send({"type": "thread_artifacts", "thread_id": thread_id})
        artifacts = await _await_event_type(client.read_event, "thread_artifacts_response")
        assert artifacts["thread_id"] == thread_id

        await client.send({"type": "thread_archive", "thread_id": thread_id})
        archive = await _await_event_type(client.read_event, "thread_operation_ack")
        assert archive["operation"] == "archive"
        assert archive["thread_id"] == thread_id
        assert archive["success"] is True

        await client.send({"type": "thread_delete", "thread_id": thread_id})
        delete_response = await _await_event_type(client.read_event, "thread_operation_ack")
        assert delete_response["operation"] == "delete"
        assert delete_response["thread_id"] == thread_id
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.xfail(reason="Contract expectation: explicit auth response handling is not fully implemented.")
async def test_websocket_auth_message_should_return_auth_response() -> None:
    """Layer B: auth message contract expects an explicit auth response."""
    port = _alloc_ephemeral_port()
    config = WebSocketConfig(enabled=True, host="127.0.0.1", port=port, tls_enabled=False)
    transport = WebSocketTransport(config)
    await transport.start(lambda msg: None)
    await asyncio.sleep(0.2)

    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    try:
        await client.connect()
        await client.send({"type": "auth", "token": "integration-token", "requested_permissions": ["read", "write"]})
        event = await _await_event_type(client.read_event, "auth_response")
        assert event["success"] is True
    finally:
        if client.is_connected:
            await client.close()
        await transport.stop()
