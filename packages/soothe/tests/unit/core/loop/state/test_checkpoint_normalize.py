"""Tests for partial StrangeLoop checkpoint blob normalization."""

from __future__ import annotations

from soothe.sloop.state.checkpoint import (
    StrangeLoopCheckpoint,
    normalize_checkpoint_data,
)


def test_normalize_register_loop_stub_validates() -> None:
    """Daemon register_loop + bind metadata must load as StrangeLoopCheckpoint."""
    loop_id = "019e3ffb-f20a-7d42-9733-e0f819bd8797"
    thread_id = "019e3ffc-a1b2-7c33-9629-3c16e1953caf"
    partial = {
        "loop_id": loop_id,
        "thread_ids": [thread_id],
        "current_thread_id": thread_id,
        "status": "running",
        "created_at": "2026-05-19T19:25:45.458000+00:00",
        "updated_at": "2026-05-19T19:25:45.458000+00:00",
    }

    normalized = normalize_checkpoint_data(partial, loop_id=loop_id)
    checkpoint = StrangeLoopCheckpoint.model_validate(normalized)

    assert checkpoint.loop_id == loop_id
    assert checkpoint.current_thread_id == thread_id
    assert checkpoint.thread_health_metrics.thread_id == thread_id
    assert checkpoint.status == "idle"
    assert checkpoint.goal_history == []


def test_normalize_created_status_maps_to_ready() -> None:
    """loop_new uses daemon-only status before the first goal runs."""
    normalized = normalize_checkpoint_data(
        {
            "loop_id": "loop-a",
            "thread_ids": [],
            "current_thread_id": "",
            "status": "created",
        },
        loop_id="loop-a",
    )
    checkpoint = StrangeLoopCheckpoint.model_validate(normalized)
    assert checkpoint.status == "idle"


def test_normalize_strips_enriched_goal_history_fields() -> None:
    """Pre-RFC-626 goal_history rows drop goal content on load."""
    normalized = normalize_checkpoint_data(
        {
            "loop_id": "loop-b",
            "thread_ids": ["t1"],
            "current_thread_id": "t1",
            "status": "idle",
            "schema_version": "4.0",
            "goal_history": [
                {
                    "goal_id": "g1",
                    "thread_id": "t1",
                    "status": "completed",
                    "goal_text": "should be stripped",
                    "loop_messages": [],
                }
            ],
        },
        loop_id="loop-b",
    )
    assert normalized["schema_version"] == "5.0"
    assert normalized["goal_history"] == [
        {"goal_id": "g1", "thread_id": "t1", "status": "completed"},
    ]
    checkpoint = StrangeLoopCheckpoint.model_validate(normalized)
    assert checkpoint.goal_history[0].goal_id == "g1"


def test_normalize_repairs_orphaned_running_loop_with_string_goal_index() -> None:
    """A JSONB-deserialized checkpoint may carry current_goal_index as a
    string (the d15f incident). ``_repair_orphaned_running_loop`` must coerce
    it to int before the ``0 <= idx`` comparison or it raises
    ``TypeError: '<=' not supported between instances of 'str' and 'int'``.
    """
    normalized = normalize_checkpoint_data(
        {
            "loop_id": "loop-c",
            "thread_ids": ["t1"],
            "current_thread_id": "t1",
            "status": "running",
            "goal_history": [
                {"goal_id": "g1", "thread_id": "t1", "status": "running"},
            ],
            "current_goal_index": "0",  # string, as from JSON/DB serialization
        },
        loop_id="loop-c",
    )
    # The repair demotes to idle and marks the goal cancelled.
    assert normalized["status"] == "idle"
    assert normalized["current_goal_index"] == -1
    assert normalized["goal_history"][0]["status"] == "cancelled"
    # Must not raise on model validation.
    checkpoint = StrangeLoopCheckpoint.model_validate(normalized)
    assert checkpoint.status == "idle"
    assert checkpoint.current_goal_index == -1
