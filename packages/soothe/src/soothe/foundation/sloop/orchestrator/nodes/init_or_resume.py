"""Loop Graph ``init_or_resume`` node (RFC-220, RFC-630).

Hydrates intent/routing from the pre-classified intake passed by the runner.
The runner handles quiz detection; loop continuation is derived in
``StrangeLoop`` from the checkpoint. This node emits the classified intake
for event streaming, surfaces the 4-class ``intake_label`` and a structural
``is_continuation`` flag onto the graph state for ``route_by_intent``, and —
for the ``trivial`` label — injects a minimal synthetic plan into
``ctx.scratch`` so the loop skips ``plan_generate`` entirely.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.foundation.sloop.cognition.trivial_plan import build_trivial_plan
from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.utils.continue_keyword import is_continue_keyword

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


def _has_prior_goal_context(ctx: LoopRuntimeContext) -> bool:
    """True when prior orchestration work exists for continuation routing."""
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


def _is_continuation(ctx: LoopRuntimeContext) -> bool:
    """Structural continuation overlay (RFC-225/RFC-226/RFC-630).

    True when ``continue_loop_mode`` is set and prior goal context exists.
    Continuation is derived from checkpoint state, not classified by the intake LLM.
    """
    if not getattr(ctx, "continue_loop_mode", False):
        return False
    return _has_prior_goal_context(ctx)


async def node_init_or_resume(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Emit pre-classified intake, surface ``intake_label``, handle trivial branch."""
    intent = ctx.loop_state.intent

    if intent is not None:
        await ctx.emit(
            "intent_classified",
            {
                "intent_type": getattr(intent, "intent_type", ""),
                "task_complexity": getattr(intent, "task_complexity", ""),
            },
        )

    intent_type = getattr(intent, "intent_type", "")
    intake_label: IntakeLabel | None = getattr(intent, "intake_label", None)
    is_continuation = _is_continuation(ctx)

    # Quiz fast-path: terminate graph before the iteration gate.
    if intent_type == "quiz":
        logger.info("[Intent] Fast path in graph: %s", intent_type)
        await ctx.emit(
            "intent_fast_path",
            {
                "intent_type": intent_type,
                "classification": intent,
            },
        )
        return {
            "intent_route": "fast_path",
            "intake_label": intake_label,
            "is_continuation": is_continuation,
            "plan_route": None,
            "assess_route": None,
            "last_outcome": None,
            "resume_synth": None,
        }

    # RFC-630: trivial branch — inject a minimal 1-step plan and skip
    # plan_generate entirely. resolve_decision reads scratch.plan_result.
    # Not applicable to continuation turns (they need plan_assess).
    if (
        intake_label == IntakeLabel.TRIVIAL
        and not is_continuation
        and not getattr(ctx, "continue_loop_mode", False)
        and not is_continue_keyword(ctx.loop_state.goal)
        and not getattr(ctx, "recovery_valid_resume", False)
    ):
        goal = getattr(intent, "goal_description", None) or ctx.loop_state.goal
        try:
            ctx.scratch.plan_result = build_trivial_plan(goal)
            logger.info("[Intent] Trivial branch: injected 1-step plan, skipping plan_generate")
        except Exception:
            logger.exception("[init_or_resume] trivial plan build failed; downgrading to complex")
            intake_label = IntakeLabel.COMPLEX

    # RFC-630: simple branch — reaches plan_generate directly (skipping
    # plan_assess), so synthesize the assessment here. Mirrors the fresh-loop
    # bypass in bounded_evidence_gather. Not for continuation turns.
    if intake_label == IntakeLabel.SIMPLE and not is_continuation:
        from ..nodes.bounded_evidence_gather import _create_fresh_loop_assessment

        ctx.scratch.plan_assessment = _create_fresh_loop_assessment()
        logger.info("[Intent] Simple branch: synthesized assessment for lightweight plan")

    return {
        "intent_route": "continue_loop",
        "intake_label": intake_label,
        "is_continuation": is_continuation,
        "plan_route": None,
        "assess_route": None,
        "last_outcome": None,
        "resume_synth": None,
    }
