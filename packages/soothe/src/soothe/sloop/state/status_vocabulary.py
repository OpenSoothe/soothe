"""Status vocabulary bridge across CE, checkpoint goal index, and loop checkpoint.

Three parallel status namespaces coexist in production (RFC-225, RFC-624, RFC-626):

- **ContextEngine** ``GoalStatus``: ``pending``, ``active``, ``completed``, …
- **Goal index** (``GoalIndexEntry.status``): ``running``, ``completed``, ``failed``, ``cancelled``
- **Loop checkpoint** (``StrangeLoopCheckpoint.status``): ``idle``, ``running``

Callers MUST translate at persistence/recovery boundaries instead of comparing raw
strings across layers.
"""

from __future__ import annotations

from typing import Literal

LoopCheckpointStatus = Literal["idle", "running"]
GoalIndexStatus = Literal["running", "completed", "failed", "cancelled"]

_GOAL_INDEX_IN_FLIGHT: frozenset[str] = frozenset({"running"})


def is_goal_index_in_flight(status: str) -> bool:
    """Return True when a checkpoint goal index entry is still in flight."""
    return status in _GOAL_INDEX_IN_FLIGHT


def suggest_loop_checkpoint_status(
    *,
    loop_status: str,
    goal_index_statuses: list[str],
) -> LoopCheckpointStatus:
    """Suggest loop-level status from goal-index rows (recovery helper).

    When the loop checkpoint says ``idle`` but goal-index rows are still
    ``running``, callers should repair toward ``running``.
    """
    if any(is_goal_index_in_flight(s) for s in goal_index_statuses):
        return "running"
    if loop_status in ("idle", "running"):
        return loop_status  # type: ignore[return-value]
    return "idle"
