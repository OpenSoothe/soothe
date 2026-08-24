"""Loop Graph ``init_or_resume`` node (RFC-904 / RFC-630).

Hydrates intent/routing from intake classified in the graph entry node.
Surfaces ``intake_label`` and ``intent_route`` for routing. Tasks route to
DISPATCH (root StepNode created there). Wired specialists set
``intent_route=wired_subagent``.

Chitchat bypass is decided here via :func:`should_bypass_chitchat_fast_path`
(loop-control phrase + intra-loop checkpoint work); routing trusts that.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.engine.execute.thread_selection import resolve_user_requested_wire_subagent
from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.utils.structural_continuation import should_bypass_chitchat_fast_path

logger = logging.getLogger(__name__)


def _graph_flags(
    *,
    intake_label: IntakeLabel | None,
    intent_route: str,
    interaction_mode: str | None = None,
) -> dict[str, Any]:
    return {
        "intent_route": intent_route,
        "intake_label": intake_label,
        "last_outcome": None,
        "dispatch_route": None,
        "reconcile_route": None,
        "root_eval_route": None,
        "interaction_mode": interaction_mode,
        "plan_rejected_terminal": None,
    }


async def node_init_or_resume(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Emit pre-classified intake and route chitchat / wired / DISPATCH."""
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

    if (
        intake_label == IntakeLabel.CHITCHAT
        and not should_bypass_chitchat_fast_path(
            getattr(ctx, "checkpoint", None),
            getattr(ctx.loop_state, "goal", None),
        )
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
            intent_route="fast_path",
            interaction_mode=getattr(ctx, "interaction_mode", None),
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
                intent_route="wired_subagent",
                interaction_mode=getattr(ctx, "interaction_mode", None),
            )

    return _graph_flags(
        intake_label=intake_label,
        intent_route="continue_loop",
        interaction_mode=getattr(ctx, "interaction_mode", None),
    )
