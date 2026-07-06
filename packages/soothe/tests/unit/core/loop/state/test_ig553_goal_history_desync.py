"""Tests for IG-553 goal_history desync fixes."""

from __future__ import annotations

from datetime import UTC, datetime

from soothe.foundation.sloop.state.checkpoint import (
    GoalIndexEntry,
    StrangeLoopCheckpoint,
    ThreadHealthMetrics,
)
from soothe.foundation.sloop.state.sloop_manager import StrangeLoopStateManager


def _goal(goal_id: str) -> GoalIndexEntry:
    now = datetime.now(UTC)
    return GoalIndexEntry(
        goal_id=goal_id,
        thread_id="thread-1",
        status="running",
        duration_ms=0,
        tokens_used=0,
        started_at=now,
        completed_at=None,
    )


def _checkpoint(*, goals: list[GoalIndexEntry] | None = None) -> StrangeLoopCheckpoint:
    now = datetime.now(UTC)
    goal_history = goals or []
    return StrangeLoopCheckpoint(
        loop_id="loop-1",
        thread_ids=["thread-1"],
        current_thread_id="thread-1",
        status="running",
        goal_history=goal_history,
        current_goal_index=len(goal_history) - 1 if goal_history else -1,
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="thread-1",
            last_updated=now,
        ),
        created_at=now,
        updated_at=now,
    )


class TestMergeLoadedCheckpoint:
    def test_preserves_richer_in_memory_goal_history(self) -> None:
        sm = StrangeLoopStateManager(loop_id="loop-1")
        mem_goal = _goal("loop-1_goal_0")
        sm._checkpoint = _checkpoint(goals=[mem_goal])
        sm._checkpoint.updated_at = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)

        loaded = _checkpoint(goals=[])
        loaded.status = "running"

        merged = sm._merge_loaded_checkpoint(loaded)
        assert len(merged.goal_history) == 1
        assert merged.goal_history[0].goal_id == "loop-1_goal_0"
        assert merged.current_goal_index == 0

    def test_keeps_db_history_when_memory_empty(self) -> None:
        sm = StrangeLoopStateManager(loop_id="loop-1")
        sm._checkpoint = None
        loaded = _checkpoint(goals=[_goal("loop-1_goal_0")])
        merged = sm._merge_loaded_checkpoint(loaded)
        assert len(merged.goal_history) == 1


class TestResolveGoalInHistory:
    def test_repairs_missing_goal(self) -> None:
        sm = StrangeLoopStateManager(loop_id="loop-1")
        checkpoint = _checkpoint(goals=[])
        goal = _goal("loop-1_goal_0")

        resolved = sm._resolve_goal_in_history(checkpoint, goal)
        assert resolved is goal
        assert len(checkpoint.goal_history) == 1
        assert checkpoint.current_goal_index == 0

    def test_finds_existing_goal(self) -> None:
        sm = StrangeLoopStateManager(loop_id="loop-1")
        goal = _goal("loop-1_goal_0")
        checkpoint = _checkpoint(goals=[goal])

        resolved = sm._resolve_goal_in_history(checkpoint, goal)
        assert resolved is goal
        assert len(checkpoint.goal_history) == 1


class TestGetCheckpoint:
    def test_returns_cached_without_db(self) -> None:
        sm = StrangeLoopStateManager(loop_id="loop-1")
        cp = _checkpoint(goals=[_goal("loop-1_goal_0")])
        sm._checkpoint = cp
        assert sm.get_checkpoint() is cp
