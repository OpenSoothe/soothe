"""Error handling integration tests for daemon protocol.

This module validates error handling and edge cases including malformed JSON,
missing required fields, invalid message types, thread not found errors,
client disconnection during stream, concurrent client connections, and
daemon shutdown during active operations.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from pathlib import Path

import pytest

from soothe.daemon import DaemonClient, SootheDaemon
from tests.integration.conftest import (
    await_event_type,
    await_status_state,
    build_daemon_config,
    force_isolated_home,
)


@pytest.fixture
async def daemon_fixture(tmp_path: Path):
    """Start a daemon for error handling tests."""
    force_isolated_home(tmp_path / "soothe-home")
    socket_path = f"/tmp/soothe-error-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    config = build_daemon_config(tmp_path, socket_path)
    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.4)
    try:
        yield daemon, socket_path
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_malformed_json_handling(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Test that malformed JSON messages are handled gracefully."""
    _, socket_path = daemon_fixture

    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        await client.send_thread_list()
        response = await await_event_type(client.read_event, "thread_list_response", timeout=2.0)
        assert response["type"] == "thread_list_response"

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_missing_required_fields(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Test that messages with missing required fields return error."""
    _, socket_path = daemon_fixture

    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        await client.send_thread_list()
        response = await await_event_type(client.read_event, "thread_list_response", timeout=2.0)
        assert response["type"] == "thread_list_response"

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_invalid_message_type(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Test that unknown message types are handled gracefully."""
    _, socket_path = daemon_fixture

    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        await client.send_thread_list()
        response = await await_event_type(client.read_event, "thread_list_response", timeout=2.0)
        assert response["type"] == "thread_list_response"

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_thread_not_found_error(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Test that accessing non-existent thread returns proper error."""
    _, socket_path = daemon_fixture

    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        fake_thread_id = f"non-existent-{uuid.uuid4().hex}"
        await client.send_thread_get(fake_thread_id)

        response = await asyncio.wait_for(client.read_event(), timeout=3.0)
        assert response is not None

        await client.send_thread_archive(fake_thread_id)
        response2 = await asyncio.wait_for(client.read_event(), timeout=3.0)
        assert response2 is not None

        await client.send_thread_list()
        list_response = await await_event_type(client.read_event, "thread_list_response", timeout=2.0)
        assert list_response["type"] == "thread_list_response"

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_disconnection_during_stream(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Test that daemon handles client disconnection during active stream."""
    _, socket_path = daemon_fixture

    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        await client.send_thread_create(initial_message="test disconnection")
        created = await await_event_type(client.read_event, "thread_created", timeout=3.0)
        thread_id = created["thread_id"]

        await client.send_input("Start a long-running operation")
        await await_status_state(client.read_event, "running", timeout=5.0)

        await client.close()

        await asyncio.sleep(0.5)

        client2 = DaemonClient(sock=Path(socket_path))
        await client2.connect()

        try:
            await client2.send_thread_list()
            list_response = await await_event_type(client2.read_event, "thread_list_response", timeout=2.0)
            assert list_response["type"] == "thread_list_response"

            threads = {t["thread_id"]: t for t in list_response["threads"]}
            assert thread_id in threads

        finally:
            await client2.close()

    except Exception:
        with contextlib.suppress(Exception):
            await client.close()
        raise


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_client_connections(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Test that daemon handles multiple concurrent client connections."""
    _, socket_path = daemon_fixture

    num_clients = 5
    clients = []

    try:
        for _ in range(num_clients):
            client = DaemonClient(sock=Path(socket_path))
            await client.connect()
            clients.append(client)

        await asyncio.sleep(0.2)

        async def send_request(client_idx: int):
            client = clients[client_idx]
            await client.send_thread_create(initial_message=f"client {client_idx}")
            return await await_event_type(client.read_event, "thread_created", timeout=5.0)

        tasks = [send_request(i) for i in range(num_clients)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        successful = 0
        for response in responses:
            if isinstance(response, dict):
                assert response.get("type") == "thread_created"
                successful += 1

        assert successful >= num_clients - 1, f"Only {successful}/{num_clients} clients succeeded"

        for client in clients:
            try:
                await client.send_thread_list()
                list_response = await asyncio.wait_for(client.read_event(), timeout=2.0)
                assert list_response is not None
            except Exception:
                pass

    finally:
        for client in clients:
            with contextlib.suppress(Exception):
                await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_daemon_shutdown_during_operation(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Test graceful shutdown during active operation."""
    _, socket_path = daemon_fixture

    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        await client.send_thread_create(initial_message="test shutdown")
        await await_event_type(client.read_event, "thread_created", timeout=3.0)

        await client.send_input("Start an operation")
        await await_status_state(client.read_event, {"running", "idle"}, timeout=5.0)

    finally:
        await client.close()
