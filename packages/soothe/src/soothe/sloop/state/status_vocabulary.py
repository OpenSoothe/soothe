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

from soothe.context.models import GoalStatus

LoopCheckpointStatus = Literal["idle", "running"]
GoalIndexStatus = Literal["running", "completed", "failed", "cancelled"]

_GOAL_INDEX_IN_FLIGHT: frozenset[str] = frozenset({"running"})
_CE_GOAL_IN_FLIGHT: frozenset[str] = frozenset({"active", "awaiting_clarification"})
_CE_TO_GOAL_INDEX: dict[str, GoalIndexStatus] = {
    "pending": "running",
    "active": "running",
    "awaiting_clarification": "running",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
    "suspended": "running",
    "blocked": "running",
    "validated": "running",
}
_GOAL_INDEX_TO_CE: dict[str, GoalStatus] = {
    "running": "active",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}


def is_goal_index_in_flight(status: str) -> bool:
    """Return True when a checkpoint goal index entry is still in flight."""
    return status in _GOAL_INDEX_IN_FLIGHT


def is_ce_goal_in_flight(status: str) -> bool:
    """Return True when a ContextEngine goal is still in flight."""
    return status in _CE_GOAL_IN_FLIGHT


def ce_goal_status_to_goal_index(status: str) -> GoalIndexStatus:
    """Map a ContextEngine goal status to checkpoint goal-index vocabulary."""
    mapped = _CE_TO_GOAL_INDEX.get(status)
    if mapped is None:
        return "running"
    return mapped


def goal_index_status_to_ce(status: str) -> GoalStatus:
    """Map a checkpoint goal-index status to ContextEngine vocabulary."""
    mapped = _GOAL_INDEX_TO_CE.get(status)
    if mapped is None:
        return "active"
    return mapped


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
