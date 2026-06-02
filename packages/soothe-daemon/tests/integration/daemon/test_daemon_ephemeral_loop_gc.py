"""Integration tests for ephemeral loop GC (IG-430)."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from soothe.core.loop.state.persistence.directory_manager import (
    PersistenceDirectoryManager,
)
from soothe_sdk.client import WebSocketClient

from soothe_daemon import SootheDaemon
from soothe_daemon.runtime.loop_gc import purge_loop_execution_data

from ..daemon_fixtures import (
    alloc_ephemeral_port,
    build_daemon_config,
    force_isolated_home,
)
from ..ws_loop_client import loop_new, request_loop_get


async def _connect_client(port: int) -> WebSocketClient:
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    await client.request_daemon_ready()
    await client.wait_for_daemon_ready()
    return client


async def run_ephemeral_gc_once(daemon: SootheDaemon) -> int:
    """Run one ephemeral GC scan (same logic as ``_periodic_ephemeral_loop_gc``)."""
    gc_cfg = daemon._daemon_config.ephemeral_loop_gc
    idle_before = datetime.now(UTC) - timedelta(hours=gc_cfg.idle_hours)
    expired = await daemon._persistence_manager.list_expired_ephemeral_loops(
        idle_before,
        limit=gc_cfg.batch_size,
    )
    purged = 0
    for row in expired:
        loop_id = str(row.get("loop_id") or "").strip()
        if loop_id and await purge_loop_execution_data(daemon, loop_id, row):
            purged += 1
    return purged


@pytest_asyncio.fixture
async def websocket_daemon_ephemeral_gc(tmp_path: Path):
    """Isolated daemon for ephemeral loop GC integration tests."""
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

        purged = await run_ephemeral_gc_once(daemon)
        assert purged >= 1

        assert await daemon._persistence_manager.get_loop_metadata(loop_id) is None
        assert not loop_dir.exists()
        assert workspace_path.exists()

        with pytest.raises(RuntimeError, match="not found"):
            await request_loop_get(client, loop_id)
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_persistent_loop_not_purged_by_ephemeral_gc(
    websocket_daemon_ephemeral_gc: tuple[SootheDaemon, int],
) -> None:
    """Persistent loops remain after GC even when last_message_at is old."""
    daemon, port = websocket_daemon_ephemeral_gc
    client = await _connect_client(port)
    try:
        loop_id = await loop_new(client, is_ephemeral=False)
        stale = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
        await daemon._persistence_manager.update_loop_metadata(
            loop_id,
            last_message_at=stale,
            status="created",
        )

        await run_ephemeral_gc_once(daemon)

        metadata = await daemon._persistence_manager.get_loop_metadata(loop_id)
        assert metadata is not None
        assert not metadata.get("is_ephemeral")

        get_resp = await request_loop_get(client, loop_id)
        assert get_resp.get("loop", {}).get("loop_id") == loop_id
    finally:
        if client.is_connected:
            await client.close()
