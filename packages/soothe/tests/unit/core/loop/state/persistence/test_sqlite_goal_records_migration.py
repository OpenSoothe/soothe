"""Tests for RFC-626 goal_records schema upgrade on SQLite open."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from soothe.foundation.sloop.state.persistence.sqlite_backend import SQLitePersistenceBackend


def _legacy_goal_records_columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as db:
        cursor = db.execute("PRAGMA table_info(goal_records)")
        return {row[1] for row in cursor.fetchall()}


def test_migrate_goal_records_drops_legacy_columns(tmp_path: Path) -> None:
    """Opening a pre-RFC-626 database upgrades goal_records to the slim index."""
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as db:
        db.execute("""
            CREATE TABLE agentloop_loops (
                loop_id TEXT PRIMARY KEY,
                thread_ids TEXT NOT NULL,
                current_thread_id TEXT NOT NULL,
                status TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE goal_records (
                goal_id TEXT PRIMARY KEY,
                loop_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                status TEXT NOT NULL,
                goal_text TEXT,
                duration_ms INTEGER DEFAULT 0,
                tokens_used INTEGER DEFAULT 0,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                loop_messages TEXT,
                evidence_summary TEXT
            )
        """)
        db.execute(
            """
            INSERT INTO agentloop_loops (loop_id, thread_ids, current_thread_id, status)
            VALUES ('loop-1', '[]', 't1', 'idle')
            """
        )
        db.execute(
            """
            INSERT INTO goal_records
                (goal_id, loop_id, thread_id, status, goal_text, started_at)
            VALUES ('g1', 'loop-1', 't1', 'completed', 'old goal body', '2026-01-01T00:00:00Z')
            """
        )
        db.commit()

    assert "goal_text" in _legacy_goal_records_columns(db_path)

    SQLitePersistenceBackend._ensure_loop_columns_on_path(db_path)

    columns = _legacy_goal_records_columns(db_path)
    assert "goal_text" not in columns
    assert columns >= {
        "goal_id",
        "loop_id",
        "thread_id",
        "status",
        "duration_ms",
        "tokens_used",
        "started_at",
        "completed_at",
    }

    with sqlite3.connect(db_path) as db:
        row = db.execute("SELECT goal_id, status FROM goal_records WHERE goal_id = 'g1'").fetchone()
    assert row == ("g1", "completed")
