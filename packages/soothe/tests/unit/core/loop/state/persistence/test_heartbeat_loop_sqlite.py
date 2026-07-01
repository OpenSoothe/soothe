"""SQLite persistence for liveness heartbeat (IG-466 follow-up: status reconciliation)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from soothe.foundation.sloop.state.persistence.sqlite_backend import SQLitePersistenceBackend


@pytest.fixture
def sqlite_backend(tmp_path: Path) -> SQLitePersistenceBackend:
    db_path = tmp_path / "loops.db"
    SQLitePersistenceBackend.initialize_database_sync(db_path)
    return SQLitePersistenceBackend(db_path=db_path, pool_size=1)


@pytest.mark.asyncio
async def test_heartbeat_loop_bumps_updated_at(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    loop_id = "loop-heartbeat-1"
    await sqlite_backend.register_loop(loop_id, [], "", status="running")

    meta_before = await sqlite_backend.get_loop_metadata(loop_id)
    assert meta_before is not None
    updated_before = meta_before["updated_at"]

    # Sleep just enough that the ISO timestamp string differs.
    await asyncio.sleep(0.01)
    await sqlite_backend.heartbeat_loop(loop_id)

    meta_after = await sqlite_backend.get_loop_metadata(loop_id)
    assert meta_after is not None
    assert meta_after["updated_at"] > updated_before


@pytest.mark.asyncio
async def test_heartbeat_loop_does_not_touch_last_message_at(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    """Heartbeat must not move the activity timestamp used by empty-loop GC."""
    loop_id = "loop-heartbeat-isolation"
    await sqlite_backend.register_loop(loop_id, [], "", status="running")
    # No counter bump → last_message_at remains NULL.
    meta_before = await sqlite_backend.get_loop_metadata(loop_id)
    assert meta_before is not None
    assert meta_before["last_message_at"] is None

    await sqlite_backend.heartbeat_loop(loop_id)

    meta_after = await sqlite_backend.get_loop_metadata(loop_id)
    assert meta_after is not None
    assert meta_after["last_message_at"] is None
    assert meta_after["human_message_count"] == 0
    assert meta_after["ai_message_count"] == 0


@pytest.mark.asyncio
async def test_heartbeat_on_missing_loop_is_silent_noop(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    # UPDATE finds no row; no exception.
    await sqlite_backend.heartbeat_loop("never-existed")
    assert await sqlite_backend.get_loop_metadata("never-existed") is None
