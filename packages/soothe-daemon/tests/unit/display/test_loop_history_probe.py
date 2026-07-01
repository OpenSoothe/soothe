"""Tests for lightweight loop history probes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from soothe_daemon.display.loop_history_probe import (
    filter_derivable_log_events,
    langgraph_checkpoint_exists,
)


@pytest.mark.asyncio
async def test_langgraph_checkpoint_exists_false_when_db_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import soothe.foundation.sloop.state.persistence.directory_manager as dm

    monkeypatch.setattr(
        dm.PersistenceDirectoryManager,
        "get_loop_checkpoint_path",
        staticmethod(lambda: tmp_path / "missing.db"),
    )
    assert await langgraph_checkpoint_exists("loop-1") is False


@pytest.mark.asyncio
async def test_langgraph_checkpoint_exists_true_when_row_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "soothe_checkpoints.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE checkpoints (thread_id TEXT NOT NULL, checkpoint BLOB, metadata BLOB)"
    )
    conn.execute(
        "INSERT INTO checkpoints (thread_id, checkpoint, metadata) VALUES (?, ?, ?)",
        ("loop-abc", b"", b"{}"),
    )
    conn.commit()
    conn.close()

    import soothe.foundation.sloop.state.persistence.directory_manager as dm

    monkeypatch.setattr(
        dm.PersistenceDirectoryManager,
        "get_loop_checkpoint_path",
        staticmethod(lambda: db_path),
    )

    assert await langgraph_checkpoint_exists("loop-abc") is True
    assert await langgraph_checkpoint_exists("other-loop") is False


def test_filter_derivable_log_events() -> None:
    rows = [
        {"kind": "conversation", "content": "hi"},
        {"kind": "debug", "content": "skip"},
        {"kind": "tool_call", "name": "grep"},
    ]
    filtered = filter_derivable_log_events(rows)
    assert len(filtered) == 2
    assert filtered[0]["kind"] == "conversation"
    assert filtered[1]["kind"] == "tool_call"
