"""Canonical goal text for planning and ContextEngine (verbatim user submission)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.sloop.state.schemas import LoopState

# CE goal statuses that still hold a resumable step DAG after interrupt.
_RESUMABLE_CE_STATUSES = frozenset({"active", "pending", "suspended", "cancelled"})


def resolve_user_request(state: LoopState) -> str:
    """Return the verbatim user submission line for this turn."""
    return (getattr(state, "goal_user_submission", None) or state.goal or "").strip()


def resolve_planning_goal(state: LoopState) -> str:
    """Return the user goal text used for planning and CE goal creation."""
    return resolve_user_request(state)


def resolve_clarification_resume_ce_goal(ce: Any, *, loop_id: str) -> Any | None:
    """Pick the in-flight ContextEngine goal to reuse on clarification resume.

    Clarification answers resume the same StrangeLoop goal; they must not create a
    new CE goal titled with the answer text (e.g. ``Approve``).

    Args:
        ce: Loaded ``ContextEngine`` instance.
        loop_id: StrangeLoop loop id for this turn.

    Returns:
        Matching active ``GoalNode``, or ``None`` when no reusable goal exists.
    """
    return _resolve_resumable_ce_goal(ce, loop_id=loop_id, statuses=frozenset({"active"}))


def resolve_interrupt_resume_ce_goal(ce: Any, *, loop_id: str) -> Any | None:
    """Pick the CE goal to reuse when resuming after user cancel / crash.

    Prefers ``active``, then ``pending`` / ``suspended``, then ``cancelled``
    (pre-IG-684 cancel path). Same ``assigned_loop_id`` matching as clarification.

    Args:
        ce: Loaded ``ContextEngine`` instance.
        loop_id: StrangeLoop loop id for this turn.

    Returns:
        Matching ``GoalNode``, or ``None`` when nothing is reusable.
    """
    return _resolve_resumable_ce_goal(ce, loop_id=loop_id, statuses=_RESUMABLE_CE_STATUSES)


def _resolve_resumable_ce_goal(
    ce: Any,
    *,
    loop_id: str,
    statuses: frozenset[str],
) -> Any | None:
    goals = list(ce.get_all_goals()) if ce is not None else []
    if not goals:
        return None

    eligible = [g for g in goals if getattr(g, "status", None) in statuses]
    if not eligible:
        return None

    exact = [g for g in eligible if getattr(g, "assigned_loop_id", None) == loop_id]
    candidates = exact or [
        g for g in eligible if getattr(g, "assigned_loop_id", None) in (None, "", loop_id)
    ]
    if not candidates:
        return None

    # Prefer active, then pending/suspended, then cancelled (legacy interrupt).
    # Among the same rank, pick the most recently updated.
    _status_rank = {"active": 0, "pending": 1, "suspended": 2, "cancelled": 3}

    def _sort_key(goal: Any) -> tuple[int, Any]:
        status = str(getattr(goal, "status", "") or "")
        rank = _status_rank.get(status, 9)
        stamp = getattr(goal, "updated_at", None) or getattr(goal, "created_at", None) or 0
        # Negate rank so max() prefers lower rank (active first).
        return (-rank, stamp)

    return max(candidates, key=_sort_key)


def apply_clarification_resume_goal_text(state: LoopState, ce_goal: Any) -> str:
    """Copy the CE goal description onto ``LoopState`` for a clarification resume.

    Args:
        state: Loop state whose ``goal`` may still hold answer text.
        ce_goal: Reused ContextEngine goal node.

    Returns:
        Restored original goal description (may be empty when CE has none).
    """
    original = (getattr(ce_goal, "description", None) or "").strip()
    if original:
        state.goal = original
        # CE stores the planning description; slash-skill submission is not
        # recoverable separately — keep resolve_user_request aligned with goal.
        state.goal_user_submission = None
    return original


__all__ = [
    "apply_clarification_resume_goal_text",
    "resolve_clarification_resume_ce_goal",
    "resolve_interrupt_resume_ce_goal",
    "resolve_planning_goal",
    "resolve_user_request",
]
