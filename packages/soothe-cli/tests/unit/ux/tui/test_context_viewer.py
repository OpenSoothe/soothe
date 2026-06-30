"""Tests for context viewer goal loading and loop-id display formatting."""

from __future__ import annotations

import json
import sqlite3

from soothe_cli.tui.widgets import context_viewer


def test_abbreviate_loop_id_uses_prefix_suffix() -> None:
    loop_id = "019f17e6-5432-4a91-b6f2-f265c9876543"
    assert context_viewer._abbreviate_loop_id(loop_id) == "019f17e6...6543"


def test_abbreviate_loop_id_keeps_short_ids() -> None:
    assert context_viewer._abbreviate_loop_id("abc123") == "abc123"


def test_load_goals_from_sqlite_reads_ce_dag_row(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "context_engine.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE ce_dag (
                loop_id TEXT PRIMARY KEY,
                dag_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO ce_dag (loop_id, dag_json, updated_at) VALUES (?, ?, ?)",
            (
                "loop-123",
                json.dumps(
                    {
                        "goals": [
                            {"id": "g1", "description": "First", "status": "active"},
                            {"id": "g2", "description": "Second", "status": "pending"},
                        ]
                    }
                ),
                "2026-06-30T00:00:00Z",
            ),
        )
        conn.commit()

    monkeypatch.setattr(context_viewer, "resolve_context_engine_db_path", lambda: db_path)
    goals = context_viewer._load_goals_from_sqlite("loop-123")
    assert [g["id"] for g in goals] == ["g1", "g2"]


def test_load_goals_from_sqlite_returns_empty_when_loop_missing(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "context_engine.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE ce_dag (
                loop_id TEXT PRIMARY KEY,
                dag_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    monkeypatch.setattr(context_viewer, "resolve_context_engine_db_path", lambda: db_path)
    assert context_viewer._load_goals_from_sqlite("missing-loop") == []
