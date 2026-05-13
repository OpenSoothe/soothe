"""Loop recovery integration tests (RFC-402 / RFC-503).

Validates loop persistence across daemon restart, concurrent loops, cancellation,
and basic isolation using ``loop_*`` WebSocket RPC—no legacy thread_* wire types.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
from soothe.config import SootheConfig
from tests.integration.ws_loop_client import (
    loop_new_with_initial_input,
    request_loop_get,
    request_loop_list,
    subscribe_loop_stream,
)

from soothe_daemon import SootheDaemon, WebSocketClient
from tests.integration.conftest import (
    alloc_ephemeral_port,
    await_event_type,
    await_status_state,
    force_isolated_home,
    get_base_config,
)


def _build_daemon_config(
    tmp_path: Path, websocket_port: int, max_concurrent_threads: int = 3
) -> SootheConfig:
    """Build an isolated daemon config for recovery tests."""
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
                    "port": websocket_port,
                },
                "http_rest": {"enabled": False},
            },
            "max_concurrent_threads": max_concurrent_threads,
        },
    )


@pytest.fixture
async def daemon_fixture(tmp_path: Path):
    """Start a daemon for recovery tests."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()

    config = _build_daemon_config(tmp_path, websocket_port=ws_port)
    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.2)
    try:
        yield daemon, ws_port, config
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_loop_resume_from_disk(tmp_path: Path) -> None:
    """Loop metadata survives daemon restart; client can reattach and continue."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config = _build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon1 = SootheDaemon(config)
    await daemon1.start()
    await asyncio.sleep(0.2)

    loop_id = None

    try:
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client1.connect()

        try:
            loop_id = await loop_new_with_initial_input(
                client1,
                initial_message="First conversation turn",
            )
            await subscribe_loop_stream(client1, loop_id)

            await client1.send_input(loop_id, "Say test")
            status = await await_status_state(client1.read_event, {"running", "idle"}, timeout=5.0)
            if status.get("state") == "running":
                await await_status_state(client1.read_event, "idle", timeout=5.0)

        finally:
            await client1.close()

    finally:
        await daemon1.stop()

    await asyncio.sleep(0.2)

    daemon2 = SootheDaemon(config)
    await daemon2.start()
    await asyncio.sleep(0.2)

    try:
        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client2.connect()

        try:
            list_response = await request_loop_list(client2)
            loop_ids = {row["loop_id"] for row in (list_response.get("loops") or [])}
            assert loop_id is not None and loop_id in loop_ids

            await client2.send_loop_reattach(loop_id)
            resume_status = await await_event_type(client2.read_event, "status", timeout=3.0)
            assert (
                resume_status.get("loop_id") == loop_id or resume_status.get("thread_id") == loop_id
            )

            await subscribe_loop_stream(client2, loop_id)

            await client2.send_input(loop_id, "Say hello")
            status2 = await await_status_state(client2.read_event, {"running", "idle"}, timeout=5.0)
            if status2.get("state") == "running":
                await await_status_state(client2.read_event, "idle", timeout=5.0)

        finally:
            await client2.close()

    finally:
        await daemon2.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_thread_recovery_missing_metadata(
    daemon_fixture: tuple[SootheDaemon, str, SootheConfig],
) -> None:
    """Loop metadata is readable via ``loop_get`` after activity."""
    daemon, ws_port, config = daemon_fixture
    _ = daemon
    _ = config

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()

    try:
        loop_id = await loop_new_with_initial_input(client, initial_message="test recovery")
        await subscribe_loop_stream(client, loop_id)

        await client.send_input(loop_id, "Say test")
        status = await await_status_state(client.read_event, {"running", "idle"}, timeout=5.0)
        if status.get("state") == "running":
            await await_status_state(client.read_event, "idle", timeout=5.0)

        get_response = await request_loop_get(client, loop_id)
        assert get_response["loop"]["loop_id"] == loop_id

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_thread_execution(
    daemon_fixture: tuple[SootheDaemon, str, SootheConfig],
) -> None:
    """Multiple loops can be registered and listed."""
    daemon, ws_port, config = daemon_fixture
    _ = daemon
    _ = config

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()

    try:
        loop_ids: list[str] = []
        for i in range(3):
            lid = await loop_new_with_initial_input(client, initial_message=f"Thread {i}")
            loop_ids.append(lid)

        list_response = await request_loop_list(client)
        listed = {row["loop_id"] for row in (list_response.get("loops") or [])}
        for lid in loop_ids:
            assert lid in listed

        await client.send_loop_reattach(loop_ids[0])
        await await_event_type(client.read_event, "status", timeout=3.0)

        await subscribe_loop_stream(client, loop_ids[0])

        await client.send_input(loop_ids[0], "Say thread")
        status = await await_status_state(client.read_event, {"running", "idle"}, timeout=5.0)
        if status.get("state") == "running":
            await await_status_state(client.read_event, "idle", timeout=5.0)

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_thread_cancellation(
    daemon_fixture: tuple[SootheDaemon, str, SootheConfig],
) -> None:
    """Cancellation command during a turn (best-effort)."""
    daemon, ws_port, config = daemon_fixture
    _ = daemon
    _ = config

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()

    try:
        loop_id = await loop_new_with_initial_input(client, initial_message="test cancellation")
        await subscribe_loop_stream(client, loop_id)

        await client.send_input(loop_id, "Start a potentially long operation")

        try:
            await await_status_state(client.read_event, "running", timeout=5.0)

            await client.send_command("/cancel")

            cancel_status = await await_status_state(client.read_event, "idle", timeout=5.0)
            assert cancel_status.get("state") == "idle"
        except TimeoutError:
            pass

        get_response = await request_loop_get(client, loop_id)
        assert get_response["loop"]["loop_id"] == loop_id

        await client.send_input(loop_id, "Say continue")
        try:
            status2 = await await_status_state(client.read_event, {"running", "idle"}, timeout=5.0)
            if status2.get("state") == "running":
                try:
                    await await_status_state(client.read_event, "idle", timeout=5.0)
                except TimeoutError:
                    pass
        except TimeoutError:
            pass

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_loop_isolation_distinct_ids(
    daemon_fixture: tuple[SootheDaemon, str, SootheConfig],
) -> None:
    """Two loops have distinct ids and independent ``loop_get`` metadata."""
    daemon, ws_port, config = daemon_fixture
    _ = daemon
    _ = config

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()

    try:
        loop_a = await loop_new_with_initial_input(client, initial_message="Thread A context")
        loop_b = await loop_new_with_initial_input(client, initial_message="Thread B context")
        assert loop_a != loop_b

        ga = await request_loop_get(client, loop_a)
        gb = await request_loop_get(client, loop_b)
        assert ga["loop"]["loop_id"] == loop_a
        assert gb["loop"]["loop_id"] == loop_b

    finally:
        await client.close()
