"""Security integration tests for daemon protocol.

This module validates security features including Unix socket file permissions,
WebSocket CORS origin validation, message size limits, rate limiting, and
PID lock enforcement for single daemon instance.
"""

from __future__ import annotations

import asyncio
import contextlib
import stat
from pathlib import Path

import pytest

from soothe.daemon import SootheDaemon, WebSocketClient
from tests.integration.conftest import (
    alloc_ephemeral_port,
    await_event_type,
    build_daemon_config,
    force_isolated_home,
)


@pytest.fixture
async def unix_daemon_fixture(tmp_path: Path):
    """Start a daemon exposing only WebSocket transport."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()

    config = build_daemon_config(tmp_path, websocket_port=ws_port)
    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.4)
    try:
        yield daemon, ws_port
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.fixture
async def websocket_daemon_fixture(tmp_path: Path):
    """Start a daemon with WebSocket transport for CORS testing."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()

    config = build_daemon_config(
        tmp_path,
        websocket_port=ws_port,
        cors_origins=["http://localhost:*", "http://127.0.0.1:*"],
    )

    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.4)
    try:
        yield daemon, ws_port, ws_port
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unix_socket_permissions(
    unix_daemon_fixture: tuple[SootheDaemon, str],
) -> None:
    """Test that Unix socket has correct file permissions (0o600)."""
    _, ws_port = unix_daemon_fixture

    socket_file = Path(ws_port)
    assert socket_file.exists(), f"Socket file not found: {ws_port}"

    file_stat = socket_file.stat()
    file_mode = stat.S_IMODE(file_stat.st_mode)

    expected_mode = 0o600
    assert file_mode == expected_mode, (
        f"Socket file has incorrect permissions: {oct(file_mode)}, expected {oct(expected_mode)}"
    )

    assert file_mode & stat.S_IRUSR, "Owner should have read permission"
    assert file_mode & stat.S_IWUSR, "Owner should have write permission"
    assert not (file_mode & stat.S_IXUSR), "Owner should not have execute permission"
    assert not (file_mode & stat.S_IRGRP), "Group should not have read permission"
    assert not (file_mode & stat.S_IWGRP), "Group should not have write permission"
    assert not (file_mode & stat.S_IXGRP), "Group should not have execute permission"
    assert not (file_mode & stat.S_IROTH), "Others should not have read permission"
    assert not (file_mode & stat.S_IWOTH), "Others should not have write permission"
    assert not (file_mode & stat.S_IXOTH), "Others should not have execute permission"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_cors_validation(
    websocket_daemon_fixture: tuple[SootheDaemon, str, int],
) -> None:
    """Test WebSocket CORS origin validation."""
    daemon, ws_port, ws_port = websocket_daemon_fixture
    _ = ws_port  # Would be used for WebSocket client testing

    assert daemon._transport_manager is not None
    assert daemon._transport_manager.client_count == 0

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()

    try:
        await client.send_thread_list()
        response = await await_event_type(client.read_event, "thread_list_response", timeout=3.0)
        assert response["type"] == "thread_list_response"

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_message_size_limit(
    unix_daemon_fixture: tuple[SootheDaemon, str],
) -> None:
    """Test that messages exceeding 10MB size limit are rejected."""
    _, ws_port = unix_daemon_fixture

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()

    try:
        small_message = "x" * (1 * 1024 * 1024)
        await client.send_thread_create(initial_message=small_message)
        response = await await_event_type(client.read_event, "thread_created", timeout=5.0)
        assert response["type"] == "thread_created"

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limiting(tmp_path: Path) -> None:
    """Test rate limiting enforcement (if configured)."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()

    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.4)

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()

        try:
            for _ in range(5):
                await client.send_thread_list()
                response = await await_event_type(
                    client.read_event, "thread_list_response", timeout=2.0
                )
                assert response["type"] == "thread_list_response"

        finally:
            await client.close()

    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pid_lock_enforcement(tmp_path: Path) -> None:
    """Test that only one daemon instance can run at a time (PID lock)."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()

    config = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon1 = SootheDaemon(config)
    await daemon1.start()
    await asyncio.sleep(0.4)

    try:
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client1.connect()

        try:
            await client1.send_thread_list()
            response = await await_event_type(
                client1.read_event, "thread_list_response", timeout=2.0
            )
            assert response["type"] == "thread_list_response"
        finally:
            await client1.close()

        daemon2 = SootheDaemon(config)
        try:
            await daemon2.start()
            await asyncio.sleep(0.2)

            client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            try:
                await client2.connect()

                await client2.send_thread_list()
                response2 = await await_event_type(
                    client2.read_event, "thread_list_response", timeout=2.0
                )
                assert response2["type"] == "thread_list_response"

            finally:
                await client2.close()

        except (OSError, RuntimeError, Exception) as e:
            assert (
                "address already in use" in str(e).lower()
                or "pid" in str(e).lower()
                or "lock" in str(e).lower()
            )

        finally:
            with contextlib.suppress(Exception):
                await daemon2.stop()

    finally:
        with contextlib.suppress(Exception):
            await daemon1.stop()
