"""Goal-entry and continuation routing helpers (RFC-226, RFC-630, IG-676).

Fresh goals use special graph entry (inject / skip-evaluate). Mid-loop goals share
the ``gather_evidence`` spine; intake tiers live in ``mid_loop_intake``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from soothe.sloop.utils.continue_keyword import is_continue_keyword

if TYPE_CHECKING:
    from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext

FRESH_LOOP_BYPASS_PREFIX = "Fresh-loop bypass:"
FRESH_LOOP_BYPASS_REASON = f"{FRESH_LOOP_BYPASS_PREFIX} no prior execution to assess."


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
    """True for the first goal with no prior loop work (IG-676 preprocess entry)."""
    if getattr(ctx, "recovery_valid_resume", False):
        return False
    if getattr(ctx, "continue_loop_mode", False):
        return False
    if has_prior_goal_context(ctx):
        return False
    return True


def is_fresh_loop_skip_evaluate(ctx: LoopRuntimeContext) -> bool:
    """True when fresh complex may skip evaluate (IG-476).

    Requires a live CE (tests without CE fall through to evaluate).
    """
    if not is_fresh_goal(ctx):
        return False
    state = ctx.loop_state
    if state.iteration != 0 or state.step_results:
        return False
    if ctx.ce is None:
        return False
    return True


def synthetic_continue_assessment(*, reasoning: str = ""):
    """Shared StatusAssessment placeholder for skip-assess / skip-evaluate routes."""
    from soothe.sloop.state.schemas import StatusAssessment

    return StatusAssessment(
        status="continue",
        goal_progress="none",
        assessment_reasoning=reasoning,
        require_goal_completion=False,
    )


def continuation_forced_plan_generate_assessment():
    """Synthetic assessment when intake complexity forbids bootstrap."""
    return synthetic_continue_assessment(reasoning="")


def fresh_loop_bypass_assessment():
    """Synthetic assessment when fresh complex skips evaluate (IG-476)."""
    return synthetic_continue_assessment(reasoning=FRESH_LOOP_BYPASS_REASON)


def bootstrap_terminal_after_execute(
    *,
    raw_user_goal: str,
    multi_phase: bool | None = None,
) -> bool:
    """Whether a bootstrap plan should skip iter=1 replan after execute.

    Chat-like and ``continue`` keyword goals remain terminal. Pass 2 ``multi_phase``
    allows replan after the first execute wave.
    """
    if is_continue_keyword(raw_user_goal):
        return True
    if multi_phase:
        return False
    return True


__all__ = [
    "FRESH_LOOP_BYPASS_PREFIX",
    "FRESH_LOOP_BYPASS_REASON",
    "bootstrap_terminal_after_execute",
    "continuation_forced_plan_generate_assessment",
    "fresh_loop_bypass_assessment",
    "has_prior_goal_context",
    "is_fresh_goal",
    "is_fresh_loop_skip_evaluate",
    "is_structural_continuation",
    "synthetic_continue_assessment",
]
