"""Canonical goal text for planning and ContextEngine (verbatim user submission)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.foundation.sloop.state.schemas import LoopState


def resolve_user_request(state: LoopState) -> str:
    """Return the verbatim user submission line for this turn."""
    return (getattr(state, "goal_user_submission", None) or state.goal or "").strip()


def resolve_planning_goal(state: LoopState) -> str:
    """Return the user goal text used for planning and CE goal creation."""
    return resolve_user_request(state)


__all__ = ["resolve_planning_goal", "resolve_user_request"]
