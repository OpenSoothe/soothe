"""SQLite persistence for ephemeral loop metadata and GC queries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from soothe.foundation.sloop.state.persistence.sqlite_backend import SQLitePersistenceBackend


@pytest.fixture
def sqlite_backend(tmp_path: Path) -> SQLitePersistenceBackend:
    db_path = tmp_path / "loops.db"
    SQLitePersistenceBackend.initialize_database_sync(db_path)
    return SQLitePersistenceBackend(db_path=db_path, pool_size=1)


@pytest.mark.asyncio
async def test_ephemeral_metadata_touch_and_list_expired(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    loop_id = "loop-ephemeral-1"
    now = datetime.now(UTC).isoformat()
    await sqlite_backend.register_loop(loop_id, [], "", status="created")
    await sqlite_backend.update_loop_metadata(
        loop_id,
        is_ephemeral=True,
        last_message_at=now,
        current_workspace="/tmp/ws",
    )

    meta = await sqlite_backend.get_loop_metadata(loop_id)
    assert meta is not None
    assert meta["is_ephemeral"] is True
    assert meta["current_workspace"] == "/tmp/ws"

    await sqlite_backend.touch_loop_last_message(loop_id)
    meta2 = await sqlite_backend.get_loop_metadata(loop_id)
    assert meta2 is not None
    assert meta2["last_message_at"] != now

    old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    await sqlite_backend.update_loop_metadata(loop_id, last_message_at=old, status="created")

    idle_before = datetime.now(UTC) - timedelta(hours=24)
    expired = await sqlite_backend.list_expired_ephemeral_loops(idle_before, limit=10)
    assert any(r["loop_id"] == loop_id for r in expired)

    await sqlite_backend.purge_loop_execution_data(loop_id)
    assert await sqlite_backend.get_loop_metadata(loop_id) is None


@pytest.mark.asyncio
async def test_persistent_loop_not_listed_as_expired(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    loop_id = "loop-persistent-1"
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    await sqlite_backend.register_loop(loop_id, [], "", status="created")
    await sqlite_backend.update_loop_metadata(
        loop_id,
        is_ephemeral=False,
        last_message_at=old,
    )

    idle_before = datetime.now(UTC) - timedelta(hours=24)
    expired = await sqlite_backend.list_expired_ephemeral_loops(idle_before, limit=10)
    assert not any(r["loop_id"] == loop_id for r in expired)
