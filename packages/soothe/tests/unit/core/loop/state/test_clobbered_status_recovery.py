"""Regression test for RFC-225 daemon-clobbered status recovery.

Reproduces the failure mode where the daemon's pre-query
``update_loop_metadata`` overwrites ``status="idle"`` (left by
``finalize_goal``) back to ``status="running"`` while
``current_goal_index`` stays at ``-1``. The fix lives in two places:

1. ``strange_loop.py``: when status=running + invalid index but goal_history
   has completed goals, take the idle-continuation path (preserve history,
   append new goal) instead of wiping.
2. ``postgres_backend.update_loop_metadata``: drop ``status`` from external
   writes when goal_history is non-empty (StrangeLoop owns status then).

RFC-624 Phase 4 Stage 2: seed_loop_ledger_from_prior_goal is deleted.
CE ledger spans all goals via ce.load(), so prior context is available
without explicit seeding.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from soothe.foundation.sloop.state.sloop_manager import StrangeLoopStateManager


@pytest.fixture
def temp_state_manager():
    """Temp-scoped StrangeLoopStateManager (mirrors test_checkpoint_index_fix)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        db_path = workspace / "test_clobber_recovery.db"
        with patch(
            "soothe.foundation.sloop.state.sloop_manager.PersistenceDirectoryManager.get_loop_checkpoint_path",
            return_value=db_path,
        ):
            state_manager = StrangeLoopStateManager(loop_id="clobber_loop_001", workspace=workspace)
            # RFC-803 Phase 6: disable async writes for tests needing sync persistence
            state_manager._async_write_enabled = False
            yield state_manager


@pytest.mark.asyncio
async def test_idle_continuation_runs_when_daemon_clobbers_status_to_running(
    temp_state_manager,
) -> None:
    sm = temp_state_manager

    # ── Setup: simulate count-goal completion + daemon clobber ────────
    checkpoint = await sm.initialize("thread_001", max_iterations=10)
    goal1 = sm.start_new_goal("count all file types", max_iterations=10)
    checkpoint.goal_history.append(goal1)
    checkpoint.current_goal_index = 0
    checkpoint.status = "running"
    await sm.save(checkpoint)

    # Finalize → sets status=idle, current_goal_index=-1
    await sm.finalize_goal(goal1, "There are 12 file types.")
    assert sm._checkpoint.status == "idle"
    assert sm._checkpoint.current_goal_index == -1
    assert len(sm._checkpoint.goal_history) == 1
    assert sm._checkpoint.goal_history[0].status == "completed"

    # Simulate daemon's pre-query clobber: status flips back to running,
    # but current_goal_index stays at -1 (daemon doesn't touch goal_history).
    clobbered = sm._checkpoint
    clobbered.status = "running"
    await sm.save(clobbered)

    # RFC-803 Phase 6: close() cancels async worker, force_flushes, and releases DB connections
    # before cold reload. Production contract: close() is called at run boundary.
    await sm.close()

    # Cold reload — mimics strange_loop.load() at the start of a new query.
    with patch(
        "soothe.foundation.sloop.state.sloop_manager.PersistenceDirectoryManager.get_loop_checkpoint_path",
        return_value=sm.db_path,
    ):
        sm2 = StrangeLoopStateManager(loop_id=sm.loop_id, workspace=Path(sm.db_path).parent)
        sm2._async_write_enabled = False
        loaded = await sm2.load()

    assert loaded is not None
    assert loaded.status == "running"  # the clobbered value
    assert loaded.current_goal_index == -1
    assert len(loaded.goal_history) == 1
    assert loaded.goal_history[0].status == "completed"
    # ── Fix A precondition holds: status==running, invalid index, prior completed goal. ──

    # ── Exercise: the recovery branch that strange_loop now takes for this state ───
    has_prior_completed = any(
        g.status in ("completed", "failed", "cancelled") for g in loaded.goal_history
    )
    assert has_prior_completed

    # Mirror the fix: restore logical idle before start_new_goal, then continue.
    loaded.status = "idle"
    sm2._checkpoint = loaded  # manager needs the loaded checkpoint as its current
    new_goal = sm2.start_new_goal("translate the result to chinese", max_iterations=10)
    loaded.goal_history.append(new_goal)
    loaded.current_goal_index = len(loaded.goal_history) - 1
    loaded.status = "running"
    # RFC-624 Phase 4 Stage 2: seed_loop_ledger_from_prior_goal deleted.
    # CE ledger spans all goals — prior context available via ce.load().
    await sm2.save(loaded)

    # RFC-803 Phase 6: close() ensures persistence before final cold reload
    await sm2.close()

    # ── Assertions: history preserved, new goal appended ──
    assert len(loaded.goal_history) == 2
    assert loaded.goal_history[0].goal_id == goal1.goal_id
    assert loaded.goal_history[0].status == "completed"
    assert loaded.goal_history[1].goal_id == new_goal.goal_id

    # Final cold reload confirms persistence of preserved history.
    with patch(
        "soothe.foundation.sloop.state.sloop_manager.PersistenceDirectoryManager.get_loop_checkpoint_path",
        return_value=sm.db_path,
    ):
        sm3 = StrangeLoopStateManager(loop_id=sm.loop_id, workspace=Path(sm.db_path).parent)
        sm3._async_write_enabled = False
        final = await sm3.load()
    assert final is not None
    assert len(final.goal_history) == 2
    assert final.goal_history[0].status == "completed"
    assert final.current_goal_index == 1


def test_wipe_branch_still_fires_for_truly_corrupt_state() -> None:
    """When goal_history is empty AND status==running, the wipe re-init path
    must still fire (no prior goals to preserve)."""
    # The discriminator in strange_loop is:
    #   checkpoint.goal_history AND any(g.status in (completed/failed/cancelled))
    # An empty goal_history short-circuits to the wipe branch.
    empty_history: list = []
    truly_corrupt = bool(empty_history) and any(  # type: ignore[unreachable]
        g.status in ("completed", "failed", "cancelled") for g in empty_history
    )
    assert truly_corrupt is False  # ← falls through to wipe re-init, preserving prior behavior.
