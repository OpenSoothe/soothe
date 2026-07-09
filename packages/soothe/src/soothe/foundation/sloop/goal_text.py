"""Canonical goal text for planning and ContextEngine (Pass 2 normalized when available)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.foundation.sloop.state.schemas import LoopState


def resolve_user_request(state: LoopState) -> str:
    """Return the verbatim user submission line for this turn."""
    return (getattr(state, "goal_user_submission", None) or state.goal or "").strip()


def resolve_planning_goal(state: LoopState) -> str:
    """Return Pass 2 ``goal_description`` when present, else ``state.goal``."""
    intent = getattr(state, "intent", None)
    if intent is not None:
        desc = getattr(intent, "goal_description", None)
        if isinstance(desc, str) and desc.strip():
            return desc.strip()
    return (state.goal or "").strip()


__all__ = ["resolve_planning_goal", "resolve_user_request"]
