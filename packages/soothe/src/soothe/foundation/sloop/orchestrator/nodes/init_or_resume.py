"""Loop Graph ``init_or_resume`` node (RFC-220, RFC-630, IG-554).

Hydrates intent/routing from intake classified in the graph entry node.
Loop continuation is derived in ``StrangeLoop`` from the checkpoint. This
node emits the classified intake for event streaming, surfaces the 3-class
``intake_label`` and a structural ``is_continuation`` flag onto the graph
state for ``route_by_intent``. Trivial labels inject a pseudo single-step plan
and route through resolve_decision → execute → goal_completion.

IG-554: Derives ``new_goal_created`` from ``recovery_valid_resume`` for the
routing guard that blocks chitchat fast-path when daemon has committed to
starting agentic work.
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

    # IG-554: new_goal_created signals daemon committed to agentic work.
    # True when NOT resuming an existing running goal. Used by routing guard
    # to block chitchat fast-path when structural admission contradicts social.
    new_goal_created = not getattr(ctx, "recovery_valid_resume", False)

    is_task = intake_label != IntakeLabel.CHITCHAT if intake_label is not None else None
    scope = (
        intake_label if intake_label is not None and intake_label != IntakeLabel.CHITCHAT else None
    )
    has_deliverable = intake_label is not None and intake_label not in (
        IntakeLabel.CHITCHAT,
        IntakeLabel.TRIVIAL,
    )

    graph_intake_fields = {
        "is_task": is_task,
        "scope": scope,
        "has_deliverable": has_deliverable,
    }

    # RFC-630 chitchat fast-path: runner emits piggybacked response directly.
    # Chitchat always bypasses StrangeLoop — even on loop continuation turns
    # (e.g. a second "who are you" in the same session).
    if (
        intake_label == IntakeLabel.CHITCHAT
        and not is_continue_keyword(ctx.loop_state.goal)
        and (getattr(intent, "chitchat_response", None) or "").strip()
    ):
        logger.info("[Intent] Fast path in graph: chitchat")
        await ctx.emit(
            "intent_fast_path",
            {
                "intent_type": "agentic",
                "classification": intent,
                "chitchat_response": intent.chitchat_response,
                "context_engine": getattr(ctx, "ce", None),
                "ce_goal_id": getattr(ctx, "ce_goal_id", None),
                "thread_id": ctx.loop_state.thread_id,
            },
        )
        return {
            "intent_route": "fast_path",
            "intake_label": intake_label,
            "is_continuation": is_continuation,
            "new_goal_created": new_goal_created,
            "plan_route": None,
            "assess_route": None,
            "last_outcome": None,
            "resume_synth": None,
            **graph_intake_fields,
        }

    # RFC-630 trivial branch: pseudo 1-step plan (goal_description), skip
    # plan_assess/plan_generate, execute on a step thread branch, then
    # goal_completion via terminal_after_execute (ledger_direct).
    if (
        intake_label == IntakeLabel.TRIVIAL
        and not is_continuation
        and not getattr(ctx, "continue_loop_mode", False)
        and not is_continue_keyword(ctx.loop_state.goal)
    ):
        from soothe.foundation.sloop.cognition.trivial_plan import build_trivial_plan

        goal_text = (getattr(intent, "goal_description", None) or ctx.loop_state.goal or "").strip()
        if not goal_text:
            goal_text = ctx.loop_state.goal
        ctx.scratch.plan_result = build_trivial_plan(goal_text)
        logger.info("[Intent] Trivial branch: pseudo plan injected (goal=%s)", goal_text[:50])
        return {
            "intent_route": "continue_loop",
            "intake_label": intake_label,
            "is_continuation": is_continuation,
            "new_goal_created": new_goal_created,
            "plan_route": None,
            "assess_route": None,
            "last_outcome": None,
            "resume_synth": None,
            **graph_intake_fields,
        }

    # RFC-630: simple branch — reaches plan_generate directly (skipping
    # plan_assess), so synthesize the assessment here. Mirrors the fresh-loop
    # bypass in bounded_evidence_gather. Applies on continuation turns too.
    if intake_label == IntakeLabel.SIMPLE:
        from ..nodes.bounded_evidence_gather import _create_fresh_loop_assessment

        ctx.scratch.plan_assessment = _create_fresh_loop_assessment()
        logger.info("[Intent] Simple branch: synthesized assessment for lightweight plan")

    return {
        "intent_route": "continue_loop",
        "intake_label": intake_label,
        "is_continuation": is_continuation,
        "new_goal_created": new_goal_created,
        "plan_route": None,
        "assess_route": None,
        "last_outcome": None,
        "resume_synth": None,
        **graph_intake_fields,
    }
