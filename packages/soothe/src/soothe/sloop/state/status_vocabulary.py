"""Status vocabulary bridge across CE, checkpoint goal index, and loop checkpoint."""

from __future__ import annotations

from typing import Literal

LoopCheckpointStatus = Literal["idle", "running", "interrupted"]

_GOAL_INDEX_IN_FLIGHT: frozenset[str] = frozenset({"running", "interrupted"})


def is_goal_index_in_flight(status: str) -> bool:
    """Return True when a checkpoint goal index entry is still in flight."""
    return status in _GOAL_INDEX_IN_FLIGHT


def suggest_loop_checkpoint_status(
    *,
    loop_status: str,
    goal_index_statuses: list[str],
) -> LoopCheckpointStatus:
    """Suggest loop-level status from goal-index rows (recovery helper)."""
    if any(is_goal_index_in_flight(s) for s in goal_index_statuses):
        return "running"
    if loop_status in ("idle", "running", "interrupted"):
        return loop_status  # type: ignore[return-value]
    return "idle"
