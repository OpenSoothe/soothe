"""Internal plan action text resolution (orchestration-only, not TUI)."""

from __future__ import annotations

from typing import Any


def resolve_plan_action_text(plan: Any) -> str:
    """Best internal action line for continuity, persistence, and fallbacks.

    Preference order:
    1. ``PlanResult.next_action`` when already derived by the planner
    2. First step ``description`` from plan-generate output

    Args:
        plan: ``PlanGeneration``, ``PlanResult``, or any object with those attributes.

    Returns:
        Non-empty action text, or ``""`` when nothing is available.
    """
    next_action = str(getattr(plan, "next_action", "") or "").strip()
    if next_action:
        return next_action

    steps = getattr(plan, "steps", None)
    if steps is None:
        decision = getattr(plan, "decision", None)
        if decision is not None:
            steps = getattr(decision, "steps", None)
    if steps:
        first_desc = str(getattr(steps[0], "description", "") or "").strip()
        if first_desc:
            return first_desc
    return ""
