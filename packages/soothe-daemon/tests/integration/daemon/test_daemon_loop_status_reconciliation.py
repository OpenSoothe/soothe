"""Integration tests for periodic loop status reconciliation (IG-466 follow-up)."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from soothe_sdk.client import WebSocketClient

from soothe_daemon import SootheDaemon
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    build_daemon_config,
    force_isolated_home,
)
from tests.integration.ws_loop_client import loop_new


async def _connect_client(port: int) -> WebSocketClient:
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    await client.request_daemon_ready()
    await client.wait_for_daemon_ready()
    return client


async def run_reconciliation_once(daemon: SootheDaemon) -> int:
    """Mirror the body of ``_periodic_loop_status_reconciliation`` for one tick."""
    cfg = daemon._daemon_config.loop_status_reconciliation
    stale_before = datetime.now(UTC) - timedelta(seconds=cfg.stale_running_seconds)

    rows = await daemon._persistence_manager.list_loops(
        status_filter="running", limit=cfg.batch_size
    )
    active_set = set(daemon._active_stream_loop_ids)
    demoted = 0
    for row in rows:
        loop_id = str(row.get("loop_id") or "").strip()
        if not loop_id or loop_id in active_set:
            continue
        updated_at_raw = row.get("updated_at")
        if not isinstance(updated_at_raw, str) or not updated_at_raw:
            continue
        try:
            updated_at = datetime.fromisoformat(updated_at_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        if updated_at >= stale_before:
            continue
        await daemon._persistence_manager.update_loop_metadata(loop_id, status="idle")
        demoted += 1
    return demoted


@pytest_asyncio.fixture
async def websocket_daemon_status_reconciliation(tmp_path: Path):
    """Isolated daemon for status-reconciliation integration tests."""
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
async def test_stale_running_loop_demoted_to_idle(
    websocket_daemon_status_reconciliation: tuple[SootheDaemon, int],
) -> None:
    """A status=running row with stale updated_at and no active runner is demoted."""
    daemon, port = websocket_daemon_status_reconciliation
    client = await _connect_client(port)
    try:
        loop_id = await loop_new(client, is_ephemeral=False)
        stale_updated = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        await daemon._persistence_manager.update_loop_metadata(
            loop_id,
            status="running",
            updated_at=stale_updated,
        )

        assert loop_id not in daemon._active_stream_loop_ids
        demoted = await run_reconciliation_once(daemon)
        assert demoted >= 1

        meta = await daemon._persistence_manager.get_loop_metadata(loop_id)
        assert meta is not None
        assert meta["status"] == "idle"
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_active_running_loop_not_demoted(
    websocket_daemon_status_reconciliation: tuple[SootheDaemon, int],
) -> None:
    """A status=running row IN the daemon's active set survives reconciliation."""
    daemon, port = websocket_daemon_status_reconciliation
    client = await _connect_client(port)
    try:
        loop_id = await loop_new(client, is_ephemeral=False)
        stale_updated = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        await daemon._persistence_manager.update_loop_metadata(
            loop_id,
            status="running",
            updated_at=stale_updated,
        )
        daemon._active_stream_loop_ids.add(loop_id)
        try:
            demoted = await run_reconciliation_once(daemon)
            assert demoted == 0

            meta = await daemon._persistence_manager.get_loop_metadata(loop_id)
            assert meta is not None
            assert meta["status"] == "running"
        finally:
            daemon._active_stream_loop_ids.discard(loop_id)
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fresh_running_loop_not_demoted(
    websocket_daemon_status_reconciliation: tuple[SootheDaemon, int],
) -> None:
    """A status=running row with recent updated_at survives even without active runner."""
    daemon, port = websocket_daemon_status_reconciliation
    client = await _connect_client(port)
    try:
        loop_id = await loop_new(client, is_ephemeral=False)
        # Bump status to running with a fresh timestamp (just now).
        await daemon._persistence_manager.update_loop_metadata(loop_id, status="running")
        # The fresh updated_at means the heartbeat is presumed still active.

        demoted = await run_reconciliation_once(daemon)
        assert demoted == 0

        meta = await daemon._persistence_manager.get_loop_metadata(loop_id)
        assert meta is not None
        assert meta["status"] == "running"
    finally:
        if client.is_connected:
            await client.close()
