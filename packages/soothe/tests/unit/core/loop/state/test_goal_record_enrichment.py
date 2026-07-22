"""Tests GoalIndexEntry persistence through SQLite (RFC-626)."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from soothe.sloop.state.execution_checkpoint import GoalIndexEntry
from soothe.sloop.state.sloop_manager import StrangeLoopStateManager

from ._sync_persist_helper import bind_sync_persist_writes


@pytest.fixture
def temp_state_manager():
    """Create a temp-scoped StrangeLoopStateManager (mirrors test_checkpoint_index_fix)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        db_path = workspace / "test_loop_checkpoints.db"
        with patch(
            "soothe.sloop.state.sloop_manager.PersistenceDirectoryManager.get_loop_checkpoint_path",
            return_value=db_path,
        ):
            state_manager = StrangeLoopStateManager(loop_id="ig445_loop_001", workspace=workspace)
            bind_sync_persist_writes(state_manager)
            yield state_manager


@pytest.mark.asyncio
async def test_goal_index_entry_round_trip_through_sqlite(temp_state_manager) -> None:
    sm = temp_state_manager
    checkpoint = await sm.initialize("thread_001")

    goal = sm.start_new_goal("verify round-trip", max_iterations=8)
    checkpoint.goal_history.append(goal)
    checkpoint.current_goal_index = 0
    checkpoint.status = "running"

    goal.status = "completed"
    goal.completed_at = datetime.now(UTC)
    goal.duration_ms = 300
    goal.tokens_used = 42
    checkpoint.status = "idle"

    await sm.save(checkpoint)
    await sm.close()

    with patch(
        "soothe.sloop.state.sloop_manager.PersistenceDirectoryManager.get_loop_checkpoint_path",
        return_value=sm.db_path,
    ):
        sm2 = StrangeLoopStateManager(loop_id=sm.loop_id, workspace=Path(sm.db_path).parent)
        loaded = await sm2.load()

    assert loaded is not None
    assert loaded.status == "idle"
    assert len(loaded.goal_history) == 1
    g: GoalIndexEntry = loaded.goal_history[0]

    assert g.goal_id == goal.goal_id
    assert g.duration_ms == 300
    assert g.tokens_used == 42
