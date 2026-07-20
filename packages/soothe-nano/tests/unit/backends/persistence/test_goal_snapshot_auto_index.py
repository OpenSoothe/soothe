"""Tests for atomic goal snapshot index allocation."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from soothe_nano.backends.persistence.display_store import DisplayCardStore


def _store_with_schema(db_path: Path) -> DisplayCardStore:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE goal_display_snapshots (
            loop_id TEXT NOT NULL,
            goal_index INTEGER NOT NULL,
            goal_id TEXT NOT NULL,
            frozen_at TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            card_count INTEGER NOT NULL,
            PRIMARY KEY (loop_id, goal_index)
        )
        """
    )
    conn.commit()
    conn.close()
    return DisplayCardStore(db_path)


def test_insert_goal_snapshot_with_auto_index_is_monotonic() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store_with_schema(Path(tmpdir) / "display.db")
        loop_id = "loop-auto-index"

        idx0, gid0 = store.insert_goal_snapshot_with_auto_index(
            loop_id,
            goal_id=None,
            snapshot={"card_count": 1, "completed_at": "2026-01-01T00:00:00Z"},
        )
        idx1, gid1 = store.insert_goal_snapshot_with_auto_index(
            loop_id,
            goal_id=None,
            snapshot={"card_count": 2, "completed_at": "2026-01-01T00:00:01Z"},
        )

        assert idx0 == 0
        assert idx1 == 1
        assert gid0 == f"{loop_id}_goal_0"
        assert gid1 == f"{loop_id}_goal_1"
        assert store.goal_snapshot_count(loop_id) == 2
