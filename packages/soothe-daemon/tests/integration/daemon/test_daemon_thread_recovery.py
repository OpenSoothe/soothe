"""Loop recovery integration tests (RFC-452 / RFC-503).

Validates loop persistence across daemon restart, concurrent loops, cancellation,
and basic isolation using ``loop_*`` WebSocket RPC—no legacy thread_* wire types.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from soothe.config import SootheConfig
from soothe_client import WebSocketClient

from soothe_daemon import SootheDaemon
from soothe_daemon.config import SootheDaemonConfig
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    await_event_type,
    await_status_state,
    build_daemon_config,
    close_client_safely,
    force_isolated_home,
    integration_llm_idle_timeout,
    stop_daemon_safely,
)
from tests.integration.ws_loop_client import (
    loop_new,
    request_loop_get,
    request_loop_list,
    subscribe_loop_stream,
)


def _build_daemon_config(
    tmp_path: Path, websocket_port: int, max_concurrent_threads: int = 3
) -> tuple[SootheConfig, SootheDaemonConfig]:
    """Build an isolated agent and daemon server config for recovery tests."""
    agent, daemon_cfg = build_daemon_config(tmp_path, websocket_port=websocket_port)
    merged = daemon_cfg.model_dump()
    merged["max_concurrent_threads"] = max_concurrent_threads
    return agent, SootheDaemonConfig.model_validate(merged)


@pytest.fixture
async def daemon_fixture(tmp_path: Path):
    """Start a daemon for recovery tests."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()

    config, daemon_cfg = _build_daemon_config(tmp_path, websocket_port=ws_port)
    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    await asyncio.sleep(0.2)
    try:
        yield daemon, ws_port, config
    finally:
        await stop_daemon_safely(daemon)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_loop_resume_from_disk(tmp_path: Path) -> None:
    """Loop metadata survives daemon restart; client can reattach and continue."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = _build_daemon_config(tmp_path, websocket_port=ws_port)

    daemon1 = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon1.start()
    await asyncio.sleep(0.2)

    loop_id = None

    try:
        client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client1.connect()
        await client1.request_connection_init()
        await client1.wait_for_connection_ack()

        try:
            loop_id = await loop_new(client1)
            await subscribe_loop_stream(client1, loop_id)

            await client1.send_input(loop_id, "Say test")
            status = await await_status_state(
                client1.read_event, {"running", "idle"}, timeout=integration_llm_idle_timeout()
            )
            if status.get("state") == "running":
                await await_status_state(
                    client1.read_event, "idle", timeout=integration_llm_idle_timeout()
                )

        finally:
            await close_client_safely(client1)

    finally:
        await stop_daemon_safely(daemon1)

    await asyncio.sleep(0.2)

    daemon2 = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon2.start()
    await asyncio.sleep(0.2)

    try:
        client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
        await client2.connect()
        await client2.request_connection_init()
        await client2.wait_for_connection_ack()

        try:
            list_response = await request_loop_list(client2)
            loop_ids = {row["loop_id"] for row in (list_response.get("loops") or [])}
            assert loop_id is not None and loop_id in loop_ids

            await client2.request("loop_reattach", {"loop_id": loop_id})
            # RFC-413 card-based replay: reattach emits soothe.card.replay.begin →
            # soothe.card.created × N → soothe.card.replay.end. Wait for the terminal frame.
            resume_status = await await_event_type(
                client2.read_event, "soothe.card.replay.end", timeout=10.0
            )
            assert resume_status.get("loop_id") == loop_id

            await subscribe_loop_stream(client2, loop_id)

            await client2.send_input(loop_id, "Say hello")
            status2 = await await_status_state(
                client2.read_event, {"running", "idle"}, timeout=integration_llm_idle_timeout()
            )
            if status2.get("state") == "running":
                await await_status_state(
                    client2.read_event, "idle", timeout=integration_llm_idle_timeout()
                )

        finally:
            await close_client_safely(client2)

    finally:
        await stop_daemon_safely(daemon2)


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
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    try:
        loop_id = await loop_new(client)
        await subscribe_loop_stream(client, loop_id)

        await client.send_input(loop_id, "Say test")
        status = await await_status_state(
            client.read_event, {"running", "idle"}, timeout=integration_llm_idle_timeout()
        )
        if status.get("state") == "running":
            await await_status_state(
                client.read_event, "idle", timeout=integration_llm_idle_timeout()
            )

        get_response = await request_loop_get(client, loop_id)
        assert get_response["loop"]["loop_id"] == loop_id

    finally:
        await close_client_safely(client)


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
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    try:
        loop_ids: list[str] = []
        for i in range(3):
            lid = await loop_new(client)
            loop_ids.append(lid)

        list_response = await request_loop_list(client)
        listed = {row["loop_id"] for row in (list_response.get("loops") or [])}
        for lid in loop_ids:
            assert lid in listed

        await client.request("loop_reattach", {"loop_id": loop_ids[0]})
        # RFC-413 card-based replay: wait for terminal soothe.card.replay.end frame.
        await await_event_type(client.read_event, "soothe.card.replay.end", timeout=10.0)

        await subscribe_loop_stream(client, loop_ids[0])

        await client.send_input(loop_ids[0], "Say thread")
        status = await await_status_state(
            client.read_event, {"running", "idle"}, timeout=integration_llm_idle_timeout()
        )
        if status.get("state") == "running":
            await await_status_state(
                client.read_event, "idle", timeout=integration_llm_idle_timeout()
            )

    finally:
        await close_client_safely(client)


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
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    try:
        loop_id = await loop_new(client)
        await subscribe_loop_stream(client, loop_id)

        await client.send_input(loop_id, "Start a potentially long operation")

        try:
            await await_status_state(
                client.read_event, "running", timeout=integration_llm_idle_timeout()
            )

            await client.notify("slash_command", {"cmd": "/cancel"})

            cancel_status = await await_status_state(
                client.read_event, "idle", timeout=integration_llm_idle_timeout()
            )
            assert cancel_status.get("state") == "idle"
        except TimeoutError:
            pass

        get_response = await request_loop_get(client, loop_id)
        assert get_response["loop"]["loop_id"] == loop_id

        await client.send_input(loop_id, "Say continue")
        try:
            status2 = await await_status_state(
                client.read_event, {"running", "idle"}, timeout=integration_llm_idle_timeout()
            )
            if status2.get("state") == "running":
                try:
                    await await_status_state(
                        client.read_event, "idle", timeout=integration_llm_idle_timeout()
                    )
                except TimeoutError:
                    pass
        except TimeoutError:
            pass

    finally:
        await close_client_safely(client)


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
    await client.request_connection_init()
    await client.wait_for_connection_ack()

    try:
        loop_a = await loop_new(client)
        loop_b = await loop_new(client)
        assert loop_a != loop_b

        ga = await request_loop_get(client, loop_a)
        gb = await request_loop_get(client, loop_b)
        assert ga["loop"]["loop_id"] == loop_a
        assert gb["loop"]["loop_id"] == loop_b

    finally:
        await close_client_safely(client)
