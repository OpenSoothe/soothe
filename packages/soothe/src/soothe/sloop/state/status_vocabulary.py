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

LoopCheckpointStatus = Literal["idle", "running", "interrupted"]
GoalIndexStatus = Literal["running", "completed", "failed", "cancelled", "interrupted"]

_GOAL_INDEX_IN_FLIGHT: frozenset[str] = frozenset({"running", "interrupted"})
_GOAL_INDEX_INTERRUPTED: frozenset[str] = frozenset({"interrupted"})


def is_goal_index_in_flight(status: str) -> bool:
    """Return True when a checkpoint goal index entry is still in flight.

    ``running`` is actively executing; ``interrupted`` is paused mid-flight by a
    user cancel or infra event and is still resumable. Both count as in-flight.
    """
    return status in _GOAL_INDEX_IN_FLIGHT


def is_goal_index_interrupted(status: str) -> bool:
    """Return True when a checkpoint goal index entry is interrupted mid-flight.

    ``interrupted`` is a *resumable* pause — distinct from terminal ``cancelled``
    and ``failed``. The cursor (iteration + completed steps) is persisted so a
    ``retry`` / ``resume`` turn picks up from the last completed step rather than
    restarting the goal.
    """
    return status in _GOAL_INDEX_INTERRUPTED


def suggest_loop_checkpoint_status(
    *,
    loop_status: str,
    goal_index_statuses: list[str],
) -> LoopCheckpointStatus:
    """Suggest loop-level status from goal-index rows (recovery helper).

    When the loop checkpoint says ``idle`` but goal-index rows are still
    ``running`` (or ``interrupted``), callers should repair toward ``running``.
    A goal row explicitly ``interrupted`` also maps to ``running`` at the
    loop checkpoint level so the next turn re-enters the goal instead of
    treating it as terminal.
    """
    if any(is_goal_index_in_flight(s) for s in goal_index_statuses):
        return "running"
    if loop_status in ("idle", "running", "interrupted"):
        return loop_status  # type: ignore[return-value]
    return "idle"
