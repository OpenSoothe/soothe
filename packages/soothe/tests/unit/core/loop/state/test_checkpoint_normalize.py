"""Tests for partial AgentLoop checkpoint blob normalization."""

from __future__ import annotations

from soothe.core.loop.state.checkpoint import (
    AgentLoopCheckpoint,
    normalize_checkpoint_data,
)


def test_normalize_register_loop_stub_validates() -> None:
    """Daemon register_loop + bind metadata must load as AgentLoopCheckpoint."""
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
    checkpoint = AgentLoopCheckpoint.model_validate(normalized)

    assert checkpoint.loop_id == loop_id
    assert checkpoint.current_thread_id == thread_id
    assert checkpoint.thread_health_metrics.thread_id == thread_id
    assert checkpoint.status == "ready_for_next_goal"
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
    checkpoint = AgentLoopCheckpoint.model_validate(normalized)
    assert checkpoint.status == "ready_for_next_goal"
