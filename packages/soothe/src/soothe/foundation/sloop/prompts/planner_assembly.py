"""Planner prompt assembly helpers (RFC-214 §4, IG-538)."""

from __future__ import annotations

from typing import Literal

from soothe.foundation.sloop.prompts.plan_ledger_projection import (
    PlannerProjectionMode,
    projected_ledger_has_goal_completion,
    resolve_planner_projection_mode,
)

PlannerCallKind = Literal["continuation", "assess", "generate"]

GOAL_PREVIEW_MAX_CHARS = 120
COMPLETION_PREVIEW_MAX_CHARS = 160


def goal_preview_text(goal: str, *, max_chars: int = GOAL_PREVIEW_MAX_CHARS) -> str:
    """Truncate active goal description for the task envelope GOAL line."""
    from soothe.foundation.sloop.prompts.user_message import _goal_text

    text = _goal_text(goal)
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


__all__ = [
    "COMPLETION_PREVIEW_MAX_CHARS",
    "GOAL_PREVIEW_MAX_CHARS",
    "PlannerCallKind",
    "PlannerProjectionMode",
    "goal_preview_text",
    "projected_ledger_has_goal_completion",
    "resolve_planner_projection_mode",
]
