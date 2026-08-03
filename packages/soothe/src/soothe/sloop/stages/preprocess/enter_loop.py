"""Loop Graph ``init_or_resume`` node (RFC-220, RFC-630, IG-554, IG-599, IG-676).

Hydrates intent/routing from intake classified in the graph entry node.
Surfaces ``intake_label``, ``is_fresh_goal``, and ``is_continuation`` for routing.
Fresh trivial/simple inject a pseudo single-step plan; mid-loop goals share the
default ``gather_evidence`` spine. Wired specialists set
``intent_route=wired_subagent`` (plan built in ``invoke_wired_subagent``).

IG-554: ``new_goal_created`` blocks chitchat fast-path when daemon already
committed to agentic work.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.engine.thread_selection import resolve_user_requested_wire_subagent
from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.orchestrator.continuation_routing import (
    is_fresh_goal,
    is_structural_continuation,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.utils.continue_keyword import is_continue_keyword

logger = logging.getLogger(__name__)


def _graph_flags(
    *,
    intake_label: IntakeLabel | None,
    is_continuation: bool,
    is_fresh: bool,
    new_goal_created: bool,
    graph_intake_fields: dict[str, Any],
    intent_route: str,
) -> dict[str, Any]:
    return {
        "intent_route": intent_route,
        "intake_label": intake_label,
        "is_continuation": is_continuation,
        "is_fresh_goal": is_fresh,
        "new_goal_created": new_goal_created,
        "plan_route": None,
        "assess_route": None,
        "last_outcome": None,
        "resume_synth": None,
        **graph_intake_fields,
    }


async def node_init_or_resume(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Emit pre-classified intake, surface ``intake_label``, handle fresh trivial/simple."""
    intent = ctx.loop_state.intent

    if intent is not None:
        intake_raw = getattr(intent, "intake_label", None)
        intake_value = getattr(intake_raw, "value", intake_raw) or ""
        complexity_raw = getattr(intent, "task_complexity", "")
        complexity_value = getattr(complexity_raw, "value", complexity_raw) or ""
        await ctx.emit(
            "intent_classified",
            {
                "intent_type": "agentic",
                "intake_label": str(intake_value),
                "task_complexity": str(complexity_value),
            },
        )

    intake_label: IntakeLabel | None = getattr(intent, "intake_label", None)
    is_continuation = is_structural_continuation(ctx)
    is_fresh = is_fresh_goal(ctx)

    # IG-554: new_goal_created signals daemon committed to agentic work.
    new_goal_created = not getattr(ctx, "recovery_valid_resume", False)

    is_task = intake_label != IntakeLabel.CHITCHAT if intake_label is not None else None
    scope = (
        intake_label if intake_label is not None and intake_label != IntakeLabel.CHITCHAT else None
    )
    has_deliverable = intake_label is not None and intake_label not in (
        IntakeLabel.CHITCHAT,
        IntakeLabel.TRIVIAL,
        IntakeLabel.SIMPLE,
    )

    graph_intake_fields = {
        "is_task": is_task,
        "scope": scope,
        "has_deliverable": has_deliverable,
    }

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
        return _graph_flags(
            intake_label=intake_label,
            is_continuation=is_continuation,
            is_fresh=is_fresh,
            new_goal_created=new_goal_created,
            graph_intake_fields=graph_intake_fields,
            intent_route="fast_path",
        )

    if intake_label != IntakeLabel.CHITCHAT:
        wire = resolve_user_requested_wire_subagent(
            routing_classification=getattr(ctx.loop_state, "routing_classification", None),
            preferred_subagent=getattr(ctx, "preferred_subagent", None),
        )
        if wire:
            logger.info(
                "[Intent] Wired subagent branch selected (subagent=%s)",
                wire,
            )
            return _graph_flags(
                intake_label=intake_label,
                is_continuation=is_continuation,
                is_fresh=is_fresh,
                new_goal_created=new_goal_created,
                graph_intake_fields=graph_intake_fields,
                intent_route="wired_subagent",
            )

    # Fresh trivial/simple only: mid-loop never injects (IG-676).
    if (
        is_fresh
        and intake_label in (IntakeLabel.TRIVIAL, IntakeLabel.SIMPLE)
        and not is_continue_keyword(ctx.loop_state.goal)
    ):
        from soothe.sloop.cognition.trivial_plan import build_trivial_plan
        from soothe.sloop.goal_text import resolve_user_request

        goal_text = resolve_user_request(ctx.loop_state)
        if not goal_text:
            goal_text = ctx.loop_state.goal
        ctx.scratch.plan_result = build_trivial_plan(
            goal_text,
            requires_tool_use=bool(getattr(intent, "requires_tool_use", False)),
        )
        logger.info(
            "[Intent] Fresh trivial/simple: pseudo plan injected (label=%s, goal=%s)",
            intake_label,
            goal_text[:50],
        )
        return _graph_flags(
            intake_label=intake_label,
            is_continuation=is_continuation,
            is_fresh=is_fresh,
            new_goal_created=new_goal_created,
            graph_intake_fields=graph_intake_fields,
            intent_route="continue_loop",
        )

    return _graph_flags(
        intake_label=intake_label,
        is_continuation=is_continuation,
        is_fresh=is_fresh,
        new_goal_created=new_goal_created,
        graph_intake_fields=graph_intake_fields,
        intent_route="continue_loop",
    )
