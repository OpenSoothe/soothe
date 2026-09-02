"""Integration tests for periodic loop status reconciliation (follow-up)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from soothe_client import WebSocketClient

from soothe_daemon import SootheDaemon
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    build_daemon_config,
    close_client_safely,
    force_isolated_home,
    stop_daemon_safely,
)
from tests.integration.ws_loop_client import loop_new


async def _connect_client(port: int) -> WebSocketClient:
    client = WebSocketClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    await client.request_connection_init()
    await client.wait_for_connection_ack()
    return client


async def run_reconciliation_once(daemon: SootheDaemon) -> int:
    """Run one status-reconciliation tick; return the number of demoted loops.

    Delegates to ``_reconcile_stale_running_loops`` (the one-shot body shared
    by both the periodic reconciliation task and the pre-GC sweep).
    """
    return await daemon._reconcile_stale_running_loops()


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
        await stop_daemon_safely(daemon)


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
        await close_client_safely(client)


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
        await close_client_safely(client)


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
        await close_client_safely(client)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_autopilot_loop_demoted_releases_worker_via_hook(
    websocket_daemon_status_reconciliation: tuple[SootheDaemon, int],
) -> None:
    """Demoting a stale autopilot-owned loop calls AutopilotService.reconcile_stale_worker.

    This closes the gap where the persistence-layer demote flipped the loop
    row to idle but left the ProcessPool slot + WorkspaceReservation pinned
    on the autopilot side (the "ghost-active worker" failure). The hook is
    fail-soft: a missing autopilot service (autopilot disabled) must not
    break reconciliation.
    """
    daemon, port = websocket_daemon_status_reconciliation
    client = await _connect_client(port)
    try:
        # Use an autopilot-owned loop id shape so is_autopilot_worker_loop_id matches.
        loop_id = "autopilot__080c916c__aabbccdd000000000000000000000001"
        stale_updated = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        await daemon._persistence_manager.update_loop_metadata(
            loop_id,
            status="running",
            updated_at=stale_updated,
        )
        assert loop_id not in daemon._active_stream_loop_ids

        # If autopilot is enabled, spy on the hook; if not, the call is a no-op
        # and reconciliation must still succeed (fail-soft).
        calls: list[str] = []
        if daemon._autopilot_service is not None:
            original = daemon._autopilot_service.reconcile_stale_worker

            async def _spy(loop_id_arg: str) -> int:
                calls.append(loop_id_arg)
                return await original(loop_id_arg)

            daemon._autopilot_service.reconcile_stale_worker = _spy  # type: ignore[method-assign]

        demoted = await run_reconciliation_once(daemon)
        assert demoted >= 1

        meta = await daemon._persistence_manager.get_loop_metadata(loop_id)
        assert meta is not None
        assert meta["status"] == "idle"

        if daemon._autopilot_service is not None:
            assert calls == [loop_id]
    finally:
        await close_client_safely(client)
