"""Tests for hot/cold checkpoint field split."""

from __future__ import annotations

from datetime import UTC, datetime

from soothe.foundation.persistence.checkpoint_split import (
    clear_persist_degraded,
    extract_cold_blob,
    extract_hot_index,
    is_persist_degraded,
    mark_persist_degraded,
    merge_hot_into_checkpoint,
)
from soothe.foundation.sloop.state.checkpoint import StrangeLoopCheckpoint, ThreadHealthMetrics


def _sample_checkpoint() -> StrangeLoopCheckpoint:
    now = datetime.now(UTC)
    return StrangeLoopCheckpoint(
        loop_id="loop-1",
        current_thread_id="loop-1",
        status="running",
        current_goal_index=0,
        total_goals_completed=1,
        goal_history=[],
        execution_checkpoint={"iteration": 2},
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="loop-1",
            last_updated=now,
        ),
        created_at=now,
        updated_at=now,
    )


def test_extract_hot_index_contains_status_fields() -> None:
    cp = _sample_checkpoint()
    hot = extract_hot_index(cp)
    assert hot["status"] == "running"
    assert hot["current_goal_index"] == 0
    assert hot["execution_checkpoint"]["iteration"] == 2


def test_extract_cold_blob_omits_hot_fields() -> None:
    cp = _sample_checkpoint()
    cold = extract_cold_blob(cp)
    assert "status" not in cold
    assert "current_goal_index" not in cold
    assert "loop_id" in cold


def test_merge_hot_into_checkpoint_overlays_index() -> None:
    base = {"loop_id": "loop-1", "status": "idle", "current_goal_index": -1}
    hot = {"status": "running", "current_goal_index": 2}
    merged = merge_hot_into_checkpoint(base, hot)
    assert merged["status"] == "running"
    assert merged["current_goal_index"] == 2


def test_persist_degraded_markers() -> None:
    cp = _sample_checkpoint()
    assert not is_persist_degraded(cp)
    mark_persist_degraded(cp)
    assert is_persist_degraded(cp)
    clear_persist_degraded(cp)
    assert not is_persist_degraded(cp)
