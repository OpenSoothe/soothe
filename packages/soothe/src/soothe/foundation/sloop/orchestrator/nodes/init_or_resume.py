"""Loop Graph ``init_or_resume`` node (RFC-220, RFC-630).

Hydrates intent/routing from intake classified in the graph entry node.
Loop continuation is derived in ``StrangeLoop`` from the checkpoint. This
node emits the classified intake for event streaming, surfaces the 3-class
``intake_label`` and a structural ``is_continuation`` flag onto the graph
state for ``route_by_intent``. Trivial labels terminate the graph early; the
runner handles CoreAgent invocation on the loop main thread.
"""

from __future__ import annotations

import logging
from typing import Any

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
                "intent_type": "agentic",
                "task_complexity": getattr(intent, "task_complexity", ""),
            },
        )

    intake_label: IntakeLabel | None = getattr(intent, "intake_label", None)
    is_continuation = _is_continuation(ctx)

    # RFC-630 trivial fast-path: runner invokes CoreAgent on the loop main thread
    # (loop_id), bypassing plan_generate / resolve_decision / execute graph nodes.
    # Continuation turns still need plan_assess and must not fast-path here.
    if (
        intake_label == IntakeLabel.TRIVIAL
        and not is_continuation
        and not getattr(ctx, "continue_loop_mode", False)
        and not is_continue_keyword(ctx.loop_state.goal)
    ):
        logger.info("[Intent] Fast path in graph: trivial")
        await ctx.emit(
            "intent_fast_path",
            {
                "fast_path_kind": "trivial",
                "intent_type": "agentic",
                "classification": intent,
                "context_engine": getattr(ctx, "ce", None),
                "ce_goal_id": getattr(ctx, "ce_goal_id", None),
                "thread_id": ctx.loop_state.thread_id,
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
