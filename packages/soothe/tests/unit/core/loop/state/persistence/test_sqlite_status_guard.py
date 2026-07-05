"""SQLite RFC-225 status clobber guard for loops with goal history."""

from __future__ import annotations

import sqlite3

import pytest

from soothe.foundation.sloop.state.persistence.sqlite_backend import SQLitePersistenceBackend


@pytest.fixture
def sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE agentloop_loops (
            loop_id TEXT PRIMARY KEY,
            status TEXT,
            resume_topic TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE goal_records (
            goal_id TEXT PRIMARY KEY,
            loop_id TEXT NOT NULL
        )
        """
    )
    conn.commit()
    yield conn
    conn.close()


def test_status_update_allowed_when_no_goals(sqlite_conn: sqlite3.Connection) -> None:
    loop_id = "loop-no-goals"
    sqlite_conn.execute(
        "INSERT INTO agentloop_loops (loop_id, status) VALUES (?, ?)",
        (loop_id, "idle"),
    )
    sqlite_conn.commit()

    backend = SQLitePersistenceBackend.__new__(SQLitePersistenceBackend)
    backend._update_loop_metadata_sync(sqlite_conn, loop_id, {"status": "running"})

    row = sqlite_conn.execute(
        "SELECT status FROM agentloop_loops WHERE loop_id = ?",
        (loop_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "running"


def test_status_update_dropped_when_goals_exist(sqlite_conn: sqlite3.Connection) -> None:
    loop_id = "loop-with-goals"
    sqlite_conn.execute(
        "INSERT INTO agentloop_loops (loop_id, status) VALUES (?, ?)",
        (loop_id, "idle"),
    )
    sqlite_conn.execute(
        "INSERT INTO goal_records (goal_id, loop_id) VALUES (?, ?)",
        ("goal-1", loop_id),
    )
    sqlite_conn.commit()

    backend = SQLitePersistenceBackend.__new__(SQLitePersistenceBackend)
    backend._update_loop_metadata_sync(sqlite_conn, loop_id, {"status": "running"})

    row = sqlite_conn.execute(
        "SELECT status FROM agentloop_loops WHERE loop_id = ?",
        (loop_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "idle"


def test_non_status_fields_still_update_when_goals_exist(sqlite_conn: sqlite3.Connection) -> None:
    loop_id = "loop-partial"
    sqlite_conn.execute(
        "INSERT INTO agentloop_loops (loop_id, status, resume_topic) VALUES (?, ?, ?)",
        (loop_id, "idle", None),
    )
    sqlite_conn.execute(
        "INSERT INTO goal_records (goal_id, loop_id) VALUES (?, ?)",
        ("goal-1", loop_id),
    )
    sqlite_conn.commit()

    backend = SQLitePersistenceBackend.__new__(SQLitePersistenceBackend)
    backend._update_loop_metadata_sync(
        sqlite_conn,
        loop_id,
        {"status": "running", "resume_topic": "follow up"},
    )

    row = sqlite_conn.execute(
        "SELECT status, resume_topic FROM agentloop_loops WHERE loop_id = ?",
        (loop_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "idle"
    assert row[1] == "follow up"
