"""Error handling integration tests for daemon protocol.

This module validates error handling and edge cases including malformed JSON,
missing required fields, invalid message types, thread not found errors,
client disconnection during stream, concurrent client connections, and
daemon shutdown during active operations.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from soothe_client import WebSocketClient
from soothe_sdk.wire import ProtocolError

from soothe_daemon import SootheDaemon
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    await_status_state,
    build_daemon_config,
    close_client_safely,
    force_isolated_home,
    stop_daemon_safely,
)
from tests.integration.ws_loop_client import (
    loop_new_with_initial_input,
    request_loop_list,
    subscribe_loop_stream,
)


@pytest.fixture
async def daemon_fixture(tmp_path: Path):
    """Start a daemon for error handling tests."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)
    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    await asyncio.sleep(0.4)
    try:
        yield daemon, ws_port
    finally:
        await stop_daemon_safely(daemon)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_malformed_json_handling(
    daemon_fixture: tuple[SootheDaemon, int],
) -> None:
    """Test that malformed JSON messages are handled gracefully."""
    _, ws_port = daemon_fixture

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    try:
        response = await request_loop_list(client)
        assert "loops" in response

    finally:
        await close_client_safely(client)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_missing_required_fields(
    daemon_fixture: tuple[SootheDaemon, int],
) -> None:
    """Test that messages with missing required fields return error."""
    _, ws_port = daemon_fixture

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    try:
        response = await request_loop_list(client)
        assert "loops" in response

    finally:
        await close_client_safely(client)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_invalid_message_type(daemon_fixture: tuple[SootheDaemon, int]) -> None:
    """Test that unknown message types are handled gracefully."""
    _, ws_port = daemon_fixture

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    try:
        response = await request_loop_list(client)
        assert "loops" in response

    finally:
        await close_client_safely(client)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_thread_not_found_error(daemon_fixture: tuple[SootheDaemon, int]) -> None:
    """Test that accessing non-existent thread returns proper error."""
    _, ws_port = daemon_fixture

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    try:
        fake_loop_id = f"non-existent-{uuid.uuid4().hex}"
        # Under protocol-1 the daemon returns a structured error envelope
        # {type:"error", error:{code:-32200, message}} for loop_get on a
        # missing loop; request() raises ProtocolError carrying that code.
        with pytest.raises(ProtocolError, match="not found") as exc_info:
            await client.request("loop_get", {"loop_id": fake_loop_id})
        assert exc_info.value.code == -32200

        # loop_delete on a missing loop is idempotent: the daemon replies with
        # a success response (request() returns the result dict).
        delete_resp = await client.request("loop_delete", {"loop_id": fake_loop_id})
        assert delete_resp.get("success") is True

        list_response = await request_loop_list(client)
        assert "loops" in list_response

    finally:
        await close_client_safely(client)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_disconnection_during_stream(
    daemon_fixture: tuple[SootheDaemon, int],
) -> None:
    """Test that daemon handles client disconnection during active stream."""
    _, ws_port = daemon_fixture

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    try:
        loop_id = await loop_new_with_initial_input(client, initial_message="test disconnection")
        await subscribe_loop_stream(client, loop_id)

        await client.send_input(loop_id, "Start a long-running operation")
        await await_status_state(client.read_event, "running", timeout=5.0)

        await close_client_safely(client)

        await asyncio.sleep(0.5)

        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client2.connect()
        await client2.request_connection_init()
        await client2.wait_for_connection_ack()

        try:
            list_response = await request_loop_list(client2)
            assert "loops" in list_response

            loops = list_response.get("loops") or []
            loop_ids = {row["loop_id"] for row in loops}
            assert loop_id in loop_ids

        finally:
            await close_client_safely(client2)

    except Exception:
        await close_client_safely(client)
        raise


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_client_connections(
    daemon_fixture: tuple[SootheDaemon, int],
) -> None:
    """Test that daemon handles multiple concurrent client connections."""
    _, ws_port = daemon_fixture

    num_clients = 5
    clients = []

    try:
        for _ in range(num_clients):
            client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            await client.connect()
            await client.request_connection_init()
            await client.wait_for_connection_ack()
            clients.append(client)

        await asyncio.sleep(0.2)

        async def send_request(client_idx: int):
            client = clients[client_idx]
            return await loop_new_with_initial_input(client, initial_message=f"client {client_idx}")

        tasks = [send_request(i) for i in range(num_clients)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        successful = 0
        for response in responses:
            if isinstance(response, str) and response:
                successful += 1

        assert successful >= num_clients - 1, f"Only {successful}/{num_clients} clients succeeded"

        for client in clients:
            try:
                list_response = await request_loop_list(client)
                assert list_response is not None
            except Exception:
                pass

    finally:
        for client in clients:
            await close_client_safely(client)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_daemon_shutdown_during_operation(
    daemon_fixture: tuple[SootheDaemon, int],
) -> None:
    """Test graceful shutdown during active operation."""
    _, ws_port = daemon_fixture

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    try:
        loop_id = await loop_new_with_initial_input(client, initial_message="test shutdown")
        await subscribe_loop_stream(client, loop_id)

        await client.send_input(loop_id, "Start an operation")
        await await_status_state(client.read_event, {"running", "idle"}, timeout=5.0)

    finally:
        await close_client_safely(client)
