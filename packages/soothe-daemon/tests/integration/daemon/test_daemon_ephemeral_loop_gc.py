"""Integration tests for periodic loop GC (IG-430 ephemeral pass + IG-466 empty pass)."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from soothe.sloop.checkpoints.directory_manager import (
    PersistenceDirectoryManager,
)
from soothe_client import WebSocketClient
from soothe_sdk.wire import ProtocolError

from soothe_daemon import SootheDaemon
from soothe_daemon.runtime.loop_gc import purge_loop_execution_data
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    build_daemon_config,
    force_isolated_home,
)
from tests.integration.ws_loop_client import loop_new, request_loop_get


async def _connect_client(port: int) -> WebSocketClient:
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()
    return client


async def run_loop_gc_once(daemon: SootheDaemon) -> tuple[int, int]:
    """Run one GC tick (both passes) and return ``(purged_ephemeral, purged_empty)``."""
    gc_cfg = daemon._daemon_config.loop_gc
    now = datetime.now(UTC)
    idle_before_ephemeral = now - timedelta(hours=gc_cfg.ephemeral_idle_hours)
    idle_before_empty = now - timedelta(hours=gc_cfg.empty_idle_hours)

    expired_ephemeral = await daemon._persistence_manager.list_expired_ephemeral_loops(
        idle_before_ephemeral,
        limit=gc_cfg.batch_size,
    )
    empty_loops = await daemon._persistence_manager.list_empty_loops(
        idle_before_empty,
        limit=gc_cfg.batch_size,
    )

    seen: set[str] = set()
    purged_ephemeral = 0
    purged_empty = 0
    for row in expired_ephemeral:
        loop_id = str(row.get("loop_id") or "").strip()
        if not loop_id or loop_id in seen:
            continue
        seen.add(loop_id)
        if await purge_loop_execution_data(daemon, loop_id, row):
            purged_ephemeral += 1
    for row in empty_loops:
        loop_id = str(row.get("loop_id") or "").strip()
        if not loop_id or loop_id in seen:
            continue
        seen.add(loop_id)
        if await purge_loop_execution_data(daemon, loop_id, row):
            purged_empty += 1
    return purged_ephemeral, purged_empty


@pytest_asyncio.fixture
async def websocket_daemon_ephemeral_gc(tmp_path: Path):
    """Isolated daemon for loop GC integration tests."""
    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    agent_cfg, daemon_cfg = build_daemon_config(tmp_path=tmp_path, websocket_port=port)
    daemon = SootheDaemon(agent_cfg, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
    await daemon.start()
    await asyncio.sleep(0.3)
    try:
        yield daemon, port
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ephemeral_loop_gc_purges_idle_loop_keeps_workspace(
    websocket_daemon_ephemeral_gc: tuple[SootheDaemon, int],
) -> None:
    """Idle ephemeral loops are purged; workspace directories are retained."""
    daemon, port = websocket_daemon_ephemeral_gc
    client = await _connect_client(port)
    try:
        loop_id = await loop_new(client, is_ephemeral=True)
        assert loop_id

        get_resp = await request_loop_get(client, loop_id)
        loop_data = get_resp.get("loop") or {}
        assert loop_data.get("is_ephemeral") is True
        assert loop_data.get("current_workspace")

        metadata = await daemon._persistence_manager.get_loop_metadata(loop_id)
        assert metadata is not None
        workspace_path = Path(str(metadata["current_workspace"]))
        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
        assert loop_dir.exists()

        stale = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        await daemon._persistence_manager.update_loop_metadata(
            loop_id,
            last_message_at=stale,
            status="created",
        )

        purged_ephemeral, purged_empty = await run_loop_gc_once(daemon)
        # Loop is both ephemeral and empty; de-dup ensures one purge total.
        assert purged_ephemeral + purged_empty == 1

        assert await daemon._persistence_manager.get_loop_metadata(loop_id) is None
        assert not loop_dir.exists()
        assert workspace_path.exists()

        # After GC, the loop is gone; loop_get returns a protocol-1 error
        # envelope {type:"error", error:{code:-32200, message:"... not found"}}
        # and request() raises ProtocolError carrying that code.
        with pytest.raises(ProtocolError, match="not found") as exc_info:
            await request_loop_get(client, loop_id)
        assert exc_info.value.code == -32200
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_loop_with_human_message_survives_empty_gc(
    websocket_daemon_ephemeral_gc: tuple[SootheDaemon, int],
) -> None:
    """Non-ephemeral loops with any human/AI message survive the empty-loop pass."""
    daemon, port = websocket_daemon_ephemeral_gc
    client = await _connect_client(port)
    try:
        loop_id = await loop_new(client, is_ephemeral=False)
        # Bump the human counter to mark the loop as non-empty.
        await daemon._persistence_manager.increment_loop_message_count(loop_id, human=1)

        stale = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
        await daemon._persistence_manager.update_loop_metadata(
            loop_id,
            last_message_at=stale,
            status="created",
        )

        purged_ephemeral, purged_empty = await run_loop_gc_once(daemon)
        assert purged_ephemeral == 0
        assert purged_empty == 0

        metadata = await daemon._persistence_manager.get_loop_metadata(loop_id)
        assert metadata is not None
        assert not metadata.get("is_ephemeral")
        assert metadata.get("human_message_count", 0) >= 1

        get_resp = await request_loop_get(client, loop_id)
        assert get_resp.get("loop", {}).get("loop_id") == loop_id
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_empty_persistent_loop_purged_by_empty_pass(
    websocket_daemon_ephemeral_gc: tuple[SootheDaemon, int],
) -> None:
    """Persistent (non-ephemeral) loops with zero counters and idle activity are purged."""
    daemon, port = websocket_daemon_ephemeral_gc
    client = await _connect_client(port)
    try:
        loop_id = await loop_new(client, is_ephemeral=False)
        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
        assert loop_dir.exists()

        # Force activity timestamp into the past, leaving counters at zero.
        stale = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
        await daemon._persistence_manager.update_loop_metadata(
            loop_id,
            last_message_at=stale,
            status="created",
        )

        purged_ephemeral, purged_empty = await run_loop_gc_once(daemon)
        assert purged_ephemeral == 0
        assert purged_empty == 1

        assert await daemon._persistence_manager.get_loop_metadata(loop_id) is None
        assert not loop_dir.exists()
    finally:
        if client.is_connected:
            await client.close()
