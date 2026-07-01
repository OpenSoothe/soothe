"""Tests GoalExecutionRecord metadata persistence through SQLite.

RFC-624 Phase 4 Stage 2 slimmed GoalExecutionRecord to metadata-only fields.
Execution payloads (messages, steps, evidence, plans) are now CE-owned and
not persisted on checkpoint goal_history rows.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from soothe.foundation.sloop.state.checkpoint import GoalExecutionRecord
from soothe.foundation.sloop.state.sloop_manager import StrangeLoopStateManager


@pytest.fixture
def temp_state_manager():
    """Create a temp-scoped StrangeLoopStateManager (mirrors test_checkpoint_index_fix)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        db_path = workspace / "test_loop_checkpoints.db"
        with patch(
            "soothe.foundation.sloop.state.sloop_manager.PersistenceDirectoryManager.get_loop_checkpoint_path",
            return_value=db_path,
        ):
            state_manager = StrangeLoopStateManager(loop_id="ig445_loop_001", workspace=workspace)
            # RFC-803 Phase 6: disable async writes for tests needing sync persistence
            state_manager._async_write_enabled = False
            yield state_manager


@pytest.mark.asyncio
async def test_goal_record_round_trip_through_sqlite(temp_state_manager) -> None:
    sm = temp_state_manager
    checkpoint = await sm.initialize("thread_001", max_iterations=8)

    # Append + persist a goal with metadata populated.
    goal = sm.start_new_goal("verify round-trip", max_iterations=8)
    checkpoint.goal_history.append(goal)
    checkpoint.current_goal_index = 0
    checkpoint.status = "running"

    goal.plan_revision_count = 3
    goal.status = "completed"
    goal.completed_at = datetime.now(UTC)
    goal.goal_completion = "done"
    goal.duration_ms = 300
    goal.tokens_used = 42
    checkpoint.status = "idle"

    await sm.save(checkpoint)

    # RFC-803 Phase 6: close() cancels async worker, force_flushes, and releases DB connections
    # before cold reload. Production contract: close() is called at run boundary (strange_loop.py:627).
    await sm.close()

    # Cold load via fresh manager pointing at the same DB.
    with patch(
        "soothe.foundation.sloop.state.sloop_manager.PersistenceDirectoryManager.get_loop_checkpoint_path",
        return_value=sm.db_path,
    ):
        sm2 = StrangeLoopStateManager(loop_id=sm.loop_id, workspace=Path(sm.db_path).parent)
        loaded = await sm2.load()

    assert loaded is not None
    assert loaded.status == "idle"
    assert len(loaded.goal_history) == 1
    g: GoalExecutionRecord = loaded.goal_history[0]

    # Identity preserved
    assert g.goal_id == goal.goal_id
    assert g.max_iterations == 8

    # Metadata fields round-tripped.
    assert g.plan_revision_count == 3
    assert g.duration_ms == 300
    assert g.tokens_used == 42
    assert g.goal_completion == "done"
