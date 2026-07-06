"""Hot/cold checkpoint field split for high-performance PostgreSQL writes."""

from __future__ import annotations

from typing import Any

from soothe.foundation.sloop.state.checkpoint import StrangeLoopCheckpoint

_PERSIST_STATUS_KEY = "persist_status"


def extract_hot_index(checkpoint: StrangeLoopCheckpoint) -> dict[str, Any]:
    """Build a small index payload for iteration-boundary writes."""
    exec_cp = dict(checkpoint.execution_checkpoint or {})
    return {
        "status": checkpoint.status,
        "current_goal_index": checkpoint.current_goal_index,
        "total_goals_completed": checkpoint.total_goals_completed,
        "current_thread_id": checkpoint.current_thread_id,
        "total_duration_ms": checkpoint.total_duration_ms,
        "total_tokens_used": checkpoint.total_tokens_used,
        "total_thread_switches": checkpoint.total_thread_switches,
        "execution_checkpoint": exec_cp,
        "updated_at": checkpoint.updated_at.isoformat() if checkpoint.updated_at else None,
    }


def extract_cold_blob(checkpoint: StrangeLoopCheckpoint) -> dict[str, Any]:
    """Build cold storage payload (goal history and auxiliary state)."""
    data = checkpoint.model_dump(mode="json")
    for key in (
        "status",
        "current_goal_index",
        "total_goals_completed",
        "current_thread_id",
        "total_duration_ms",
        "total_tokens_used",
        "total_thread_switches",
        "execution_checkpoint",
        "updated_at",
    ):
        data.pop(key, None)
    return data


def merge_hot_into_checkpoint(
    checkpoint_data: dict[str, Any],
    hot_index: dict[str, Any],
) -> dict[str, Any]:
    """Overlay hot index fields onto full checkpoint_data for load."""
    merged = dict(checkpoint_data)
    for key in (
        "status",
        "current_goal_index",
        "total_goals_completed",
        "current_thread_id",
        "total_duration_ms",
        "total_tokens_used",
        "total_thread_switches",
        "execution_checkpoint",
    ):
        if key in hot_index:
            merged[key] = hot_index[key]
    if hot_index.get("updated_at"):
        merged["updated_at"] = hot_index["updated_at"]
    return merged


def mark_persist_degraded(checkpoint: StrangeLoopCheckpoint) -> None:
    """Tag execution checkpoint when durable flush failed."""
    exec_cp = dict(checkpoint.execution_checkpoint or {})
    exec_cp[_PERSIST_STATUS_KEY] = "degraded"
    checkpoint.execution_checkpoint = exec_cp


def clear_persist_degraded(checkpoint: StrangeLoopCheckpoint) -> None:
    """Clear persist degraded marker after successful durable flush."""
    exec_cp = dict(checkpoint.execution_checkpoint or {})
    exec_cp.pop(_PERSIST_STATUS_KEY, None)
    checkpoint.execution_checkpoint = exec_cp


def is_persist_degraded(checkpoint: StrangeLoopCheckpoint) -> bool:
    """Return True when checkpoint index marks a failed durable persist."""
    exec_cp = checkpoint.execution_checkpoint or {}
    return exec_cp.get(_PERSIST_STATUS_KEY) == "degraded"
