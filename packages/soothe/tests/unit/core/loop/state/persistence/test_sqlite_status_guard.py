"""SQLite RFC-225 status clobber guard for loops with goal history."""

from __future__ import annotations

import sqlite3

import pytest

from soothe.sloop.checkpoints.sqlite_backend import SQLitePersistenceBackend


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
            loop_id TEXT NOT NULL,
            status TEXT NOT NULL,
            completed_at TEXT
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
        "INSERT INTO goal_records (goal_id, loop_id, status) VALUES (?, ?, ?)",
        ("goal-1", loop_id, "completed"),
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
        "INSERT INTO goal_records (goal_id, loop_id, status) VALUES (?, ?, ?)",
        ("goal-1", loop_id, "completed"),
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


def test_force_status_overrides_goal_guard(sqlite_conn: sqlite3.Connection) -> None:
    """Reconciler force-demote must persist ``status`` even with goals.

    Regression for the d15f incident: the stale-loop reconciler logged
    ``running -> idle`` every 5 min forever because the RFC-225 guard
    silently dropped the ``status`` write for a loop with goal_records.
    ``force_status=True`` is the authoritative bypass for confirmed-dead
    zombies (no active runner, past the staleness threshold).
    """
    loop_id = "loop-zombie"
    sqlite_conn.execute(
        "INSERT INTO agentloop_loops (loop_id, status) VALUES (?, ?)",
        (loop_id, "running"),
    )
    sqlite_conn.execute(
        "INSERT INTO goal_records (goal_id, loop_id, status) VALUES (?, ?, ?)",
        ("goal-2", loop_id, "running"),
    )
    sqlite_conn.commit()

    backend = SQLitePersistenceBackend.__new__(SQLitePersistenceBackend)
    backend._update_loop_metadata_sync(
        sqlite_conn,
        loop_id,
        {"status": "idle"},
        force_status=True,
    )

    row = sqlite_conn.execute(
        "SELECT status FROM agentloop_loops WHERE loop_id = ?",
        (loop_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "idle"


def test_mark_running_goals_failed_closes_orphaned_goals(
    sqlite_conn: sqlite3.Connection,
) -> None:
    """Crashed-runner goals stuck in ``running`` are closed to ``failed``."""
    loop_id = "loop-crash"
    sqlite_conn.execute(
        "INSERT INTO agentloop_loops (loop_id, status) VALUES (?, ?)",
        (loop_id, "running"),
    )
    sqlite_conn.execute(
        "INSERT INTO goal_records (goal_id, loop_id, status) VALUES (?, ?, ?)",
        ("goal-done", loop_id, "completed"),
    )
    sqlite_conn.execute(
        "INSERT INTO goal_records (goal_id, loop_id, status) VALUES (?, ?, ?)",
        ("goal-stuck", loop_id, "running"),
    )
    sqlite_conn.commit()

    backend = SQLitePersistenceBackend.__new__(SQLitePersistenceBackend)
    closed = backend._mark_running_goals_failed_sync(sqlite_conn, loop_id)
    assert closed == 1

    rows = sqlite_conn.execute(
        "SELECT goal_id, status, completed_at FROM goal_records WHERE loop_id = ? ORDER BY goal_id",
        (loop_id,),
    ).fetchall()
    assert rows[0] == ("goal-done", "completed", None)
    assert rows[1][0] == "goal-stuck"
    assert rows[1][1] == "failed"
    assert rows[1][2] is not None
