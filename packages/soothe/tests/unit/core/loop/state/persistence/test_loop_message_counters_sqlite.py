"""SQLite persistence for empty-loop GC: message counters + list_empty_loops (IG-466)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from soothe.foundation.loop.state.persistence.sqlite_backend import SQLitePersistenceBackend


@pytest.fixture
def sqlite_backend(tmp_path: Path) -> SQLitePersistenceBackend:
    db_path = tmp_path / "loops.db"
    SQLitePersistenceBackend.initialize_database_sync(db_path)
    return SQLitePersistenceBackend(db_path=db_path, pool_size=1)


@pytest.mark.asyncio
async def test_register_loop_initial_counters_are_zero(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    loop_id = "loop-counters-init"
    await sqlite_backend.register_loop(loop_id, [], "", status="created")

    meta = await sqlite_backend.get_loop_metadata(loop_id)
    assert meta is not None
    assert meta["human_message_count"] == 0
    assert meta["ai_message_count"] == 0


@pytest.mark.asyncio
async def test_increment_human_counter_updates_metadata(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    loop_id = "loop-human-bump"
    await sqlite_backend.register_loop(loop_id, [], "", status="created")

    await sqlite_backend.increment_loop_message_count(loop_id, human=1)

    meta = await sqlite_backend.get_loop_metadata(loop_id)
    assert meta is not None
    assert meta["human_message_count"] == 1
    assert meta["ai_message_count"] == 0
    assert meta["last_message_at"] is not None


@pytest.mark.asyncio
async def test_increment_ai_counter_updates_metadata(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    loop_id = "loop-ai-bump"
    await sqlite_backend.register_loop(loop_id, [], "", status="created")

    await sqlite_backend.increment_loop_message_count(loop_id, ai=1)

    meta = await sqlite_backend.get_loop_metadata(loop_id)
    assert meta is not None
    assert meta["human_message_count"] == 0
    assert meta["ai_message_count"] == 1
    assert meta["last_message_at"] is not None


@pytest.mark.asyncio
async def test_concurrent_increments_both_land(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    loop_id = "loop-concurrent"
    await sqlite_backend.register_loop(loop_id, [], "", status="created")

    await asyncio.gather(
        sqlite_backend.increment_loop_message_count(loop_id, human=1),
        sqlite_backend.increment_loop_message_count(loop_id, ai=1),
        sqlite_backend.increment_loop_message_count(loop_id, human=2),
    )

    meta = await sqlite_backend.get_loop_metadata(loop_id)
    assert meta is not None
    assert meta["human_message_count"] == 3
    assert meta["ai_message_count"] == 1


@pytest.mark.asyncio
async def test_increment_zero_zero_is_noop(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    loop_id = "loop-noop"
    await sqlite_backend.register_loop(loop_id, [], "", status="created")
    meta_before = await sqlite_backend.get_loop_metadata(loop_id)
    assert meta_before is not None
    last_before = meta_before["last_message_at"]

    await sqlite_backend.increment_loop_message_count(loop_id, human=0, ai=0)

    meta_after = await sqlite_backend.get_loop_metadata(loop_id)
    assert meta_after is not None
    assert meta_after["human_message_count"] == 0
    assert meta_after["ai_message_count"] == 0
    assert meta_after["last_message_at"] == last_before


@pytest.mark.asyncio
async def test_increment_on_missing_loop_is_silent_noop(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    # No register_loop — the UPDATE finds no row but does not raise.
    await sqlite_backend.increment_loop_message_count("nonexistent", human=1)
    assert await sqlite_backend.get_loop_metadata("nonexistent") is None


@pytest.mark.asyncio
async def test_list_empty_loops_includes_zero_counters_past_threshold(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    loop_id = "loop-empty-idle"
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    await sqlite_backend.register_loop(loop_id, [], "", status="created")
    # Force activity timestamp into the past; counters stay at zero.
    await sqlite_backend.update_loop_metadata(loop_id, last_message_at=old)

    idle_before = datetime.now(UTC) - timedelta(hours=24)
    empty = await sqlite_backend.list_empty_loops(idle_before, limit=10)
    assert any(r["loop_id"] == loop_id for r in empty)


@pytest.mark.asyncio
async def test_list_empty_loops_excludes_loop_with_human_counter(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    loop_id = "loop-has-human"
    await sqlite_backend.register_loop(loop_id, [], "", status="created")
    await sqlite_backend.increment_loop_message_count(loop_id, human=1)
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    await sqlite_backend.update_loop_metadata(loop_id, last_message_at=old)

    idle_before = datetime.now(UTC) - timedelta(hours=24)
    empty = await sqlite_backend.list_empty_loops(idle_before, limit=10)
    assert not any(r["loop_id"] == loop_id for r in empty)


@pytest.mark.asyncio
async def test_list_empty_loops_excludes_loop_with_ai_counter(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    loop_id = "loop-has-ai"
    await sqlite_backend.register_loop(loop_id, [], "", status="created")
    await sqlite_backend.increment_loop_message_count(loop_id, ai=1)
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    await sqlite_backend.update_loop_metadata(loop_id, last_message_at=old)

    idle_before = datetime.now(UTC) - timedelta(hours=24)
    empty = await sqlite_backend.list_empty_loops(idle_before, limit=10)
    assert not any(r["loop_id"] == loop_id for r in empty)


@pytest.mark.asyncio
async def test_list_empty_loops_excludes_running_loop(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    loop_id = "loop-running-empty"
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    await sqlite_backend.register_loop(loop_id, [], "", status="running")
    await sqlite_backend.update_loop_metadata(loop_id, last_message_at=old)

    idle_before = datetime.now(UTC) - timedelta(hours=24)
    empty = await sqlite_backend.list_empty_loops(idle_before, limit=10)
    assert not any(r["loop_id"] == loop_id for r in empty)


@pytest.mark.asyncio
async def test_list_empty_loops_respects_idle_threshold(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    # Recent activity — counter still zero but last_message_at is now → excluded.
    loop_id = "loop-recent-empty"
    await sqlite_backend.register_loop(loop_id, [], "", status="created")
    await sqlite_backend.update_loop_metadata(
        loop_id, last_message_at=datetime.now(UTC).isoformat()
    )

    idle_before = datetime.now(UTC) - timedelta(hours=24)
    empty = await sqlite_backend.list_empty_loops(idle_before, limit=10)
    assert not any(r["loop_id"] == loop_id for r in empty)


@pytest.mark.asyncio
async def test_list_empty_loops_uses_created_at_when_last_message_null(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    # Bootstrap-only: register_loop sets created_at=now; last_message_at left NULL.
    # We force created_at into the past via SQL directly to simulate aging.
    loop_id = "loop-coalesce-fallback"
    await sqlite_backend.register_loop(loop_id, [], "", status="created")
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()

    def _backdate_created_at(conn, lid: str, ts: str) -> None:
        conn.execute("UPDATE agentloop_loops SET created_at = ? WHERE loop_id = ?", (ts, lid))
        conn.commit()

    await sqlite_backend._writer_to_thread(_backdate_created_at, loop_id, old)

    idle_before = datetime.now(UTC) - timedelta(hours=24)
    empty = await sqlite_backend.list_empty_loops(idle_before, limit=10)
    assert any(r["loop_id"] == loop_id for r in empty)


@pytest.mark.asyncio
async def test_list_empty_loops_honors_limit(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    for i in range(5):
        lid = f"loop-bulk-{i}"
        await sqlite_backend.register_loop(lid, [], "", status="created")
        await sqlite_backend.update_loop_metadata(lid, last_message_at=old)

    idle_before = datetime.now(UTC) - timedelta(hours=24)
    empty = await sqlite_backend.list_empty_loops(idle_before, limit=3)
    assert len(empty) == 3


@pytest.mark.asyncio
async def test_list_loops_default_includes_empty(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    """Default list_loops behavior preserves the unfiltered view."""
    await sqlite_backend.register_loop("loop-empty", [], "", status="created")
    await sqlite_backend.register_loop("loop-non-empty", [], "", status="created")
    await sqlite_backend.increment_loop_message_count("loop-non-empty", human=1)

    rows = await sqlite_backend.list_loops()
    loop_ids = {r["loop_id"] for r in rows}
    assert loop_ids == {"loop-empty", "loop-non-empty"}


@pytest.mark.asyncio
async def test_list_loops_exclude_empty_filters_zero_counters(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    """exclude_empty=True hides loops with zero human and zero AI messages."""
    await sqlite_backend.register_loop("loop-empty", [], "", status="created")
    await sqlite_backend.register_loop("loop-with-human", [], "", status="created")
    await sqlite_backend.increment_loop_message_count("loop-with-human", human=1)
    await sqlite_backend.register_loop("loop-with-ai", [], "", status="created")
    await sqlite_backend.increment_loop_message_count("loop-with-ai", ai=1)

    rows = await sqlite_backend.list_loops(exclude_empty=True)
    loop_ids = {r["loop_id"] for r in rows}
    assert loop_ids == {"loop-with-human", "loop-with-ai"}
    # Counters are surfaced on the row payload.
    for row in rows:
        assert "human_message_count" in row
        assert "ai_message_count" in row


@pytest.mark.asyncio
async def test_list_loops_combines_status_and_exclude_empty(
    sqlite_backend: SQLitePersistenceBackend,
) -> None:
    """Both filters apply together (AND)."""
    await sqlite_backend.register_loop("loop-created-empty", [], "", status="created")
    await sqlite_backend.register_loop("loop-created-with-msg", [], "", status="created")
    await sqlite_backend.increment_loop_message_count("loop-created-with-msg", human=1)
    await sqlite_backend.register_loop("loop-running-with-msg", [], "", status="running")
    await sqlite_backend.increment_loop_message_count("loop-running-with-msg", human=1)

    rows = await sqlite_backend.list_loops(status_filter="created", exclude_empty=True)
    loop_ids = {r["loop_id"] for r in rows}
    assert loop_ids == {"loop-created-with-msg"}
