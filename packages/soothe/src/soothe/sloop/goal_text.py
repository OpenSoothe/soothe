"""Canonical goal text for planning and ContextEngine (verbatim user submission)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.sloop.state.schemas import LoopState


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
    goals = list(ce.get_all_goals()) if ce is not None else []
    if not goals:
        return None

    active = [g for g in goals if getattr(g, "status", None) == "active"]
    if not active:
        return None

    exact = [g for g in active if getattr(g, "assigned_loop_id", None) == loop_id]
    candidates = exact or [
        g for g in active if getattr(g, "assigned_loop_id", None) in (None, "", loop_id)
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    def _sort_key(goal: Any) -> Any:
        return getattr(goal, "updated_at", None) or getattr(goal, "created_at", None) or 0

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
    "resolve_planning_goal",
    "resolve_user_request",
]
