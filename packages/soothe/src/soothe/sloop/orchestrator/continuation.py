"""Goal-entry and continuation policy for StrangeLoop preprocess.

Fresh vs structural-continuation detection for ``enter_loop`` routing.
Plan-spine mid-loop helpers (lightweight generate, inventory, bypass assess)
were removed with LLMPlanner.
"""

from __future__ import annotations

from typing import Any

FRESH_LOOP_BYPASS_PREFIX = "Fresh-loop bypass:"
FRESH_LOOP_BYPASS_REASON = f"{FRESH_LOOP_BYPASS_PREFIX} no prior execution to assess."

__all__ = [
    "FRESH_LOOP_BYPASS_PREFIX",
    "FRESH_LOOP_BYPASS_REASON",
    "has_prior_goal_context",
    "is_fresh_goal",
    "is_structural_continuation",
]


def has_prior_goal_context(ctx: Any) -> bool:
    """True when prior orchestration work exists (CE DAG or checkpoint history)."""
    ce = getattr(ctx, "ce", None)
    current_id = getattr(ctx, "ce_goal_id", None)
    if ce is not None:
        for goal in ce.get_all_goals():
            if current_id and goal.id == current_id:
                continue
            completed_steps = [s for s in goal.steps.nodes.values() if s.status == "completed"]
            if completed_steps or goal.action_history:
                return True
            if goal.status in ("completed", "cancelled", "failed"):
                return True
    checkpoint = getattr(ctx, "checkpoint", None)
    return bool(checkpoint and len(checkpoint.goal_history) >= 2)


def is_structural_continuation(ctx: Any) -> bool:
    """True when ``continue_loop_mode`` and prior goal context exist."""
    if not getattr(ctx, "continue_loop_mode", False):
        return False
    return has_prior_goal_context(ctx)


def is_fresh_goal(ctx: Any) -> bool:
    """True for the first goal with no prior loop work (preprocess entry)."""
    if getattr(ctx, "recovery_valid_resume", False):
        return False
    if getattr(ctx, "continue_loop_mode", False):
        return False
    if has_prior_goal_context(ctx):
        return False
    return True
