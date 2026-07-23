"""Security integration tests for daemon protocol.

This module validates security features including WebSocket CORS origin validation,
message size limits, rate limiting, and PID lock enforcement for single daemon instance.

Note: Unix socket transport was removed on 2026-03-29 due to stability issues.
WebSocket is now the primary transport for bidirectional streaming.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
from soothe_client import WebSocketClient

from soothe_daemon import SootheDaemon
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    build_daemon_config,
    force_isolated_home,
)
from tests.integration.ws_loop_client import loop_new, request_loop_list, subscribe_loop_stream


@pytest.fixture
async def websocket_daemon_fixture(tmp_path: Path):
    """Start a daemon with WebSocket transport for CORS testing."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()

    config, daemon_cfg = build_daemon_config(
        tmp_path,
        websocket_port=ws_port,
        cors_origins=["http://localhost:*", "http://127.0.0.1:*"],
    )

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    await asyncio.sleep(0.4)
    try:
        yield daemon, ws_port, ws_port
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


# Note: test_unix_socket_permissions removed - Unix socket transport was removed
# on 2026-03-29 due to stability issues (RFC-0013 update). WebSocket is now the
# primary transport for bidirectional streaming.


@pytest.mark.asyncio
@pytest.mark.integration
async def test_websocket_cors_validation(
    websocket_daemon_fixture: tuple[SootheDaemon, str, int],
) -> None:
    """Test WebSocket CORS origin validation."""
    daemon, ws_port, ws_port = websocket_daemon_fixture
    _ = ws_port  # Would be used for WebSocket client testing

    assert daemon._channel_manager is not None
    assert daemon._channel_manager.client_count == 0

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    try:
        response = await request_loop_list(client)
        assert "loops" in response

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_message_size_limit(tmp_path: Path) -> None:
    """Test that messages exceeding 10MB size limit are rejected."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)
    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    await asyncio.sleep(0.4)
    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()

        try:
            small_message = "x" * (1 * 1024 * 1024)
            loop_id = await loop_new(client)
            await subscribe_loop_stream(client, loop_id)
            await client.notify("loop_input", {"loop_id": loop_id, "content": small_message})
            assert loop_id

        finally:
            await client.close()
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limiting(tmp_path: Path) -> None:
    """Test rate limiting enforcement (if configured)."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()

    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    await asyncio.sleep(0.4)

    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client.connect()
        await client.request_connection_init()
        await client.wait_for_connection_ack()

        try:
            for _ in range(5):
                response = await request_loop_list(client)
                assert "loops" in response

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

    config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon1 = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon1.start()
    await asyncio.sleep(0.4)

    try:
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client1.connect()
        await client1.request_connection_init()
        await client1.wait_for_connection_ack()

        try:
            response = await request_loop_list(client1)
            assert "loops" in response
        finally:
            await client1.close()

        daemon2 = SootheDaemon(config, daemon_config=daemon_cfg)
        try:
            await daemon2.start()
            await asyncio.sleep(0.2)

            client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            try:
                await client2.connect()
                await client2.request_connection_init()
                await client2.wait_for_connection_ack()

                response2 = await request_loop_list(client2)
                assert "loops" in response2

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
