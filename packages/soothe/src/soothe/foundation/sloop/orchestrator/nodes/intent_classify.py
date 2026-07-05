"""Loop Graph entry node: LLM intake classification (RFC-220, RFC-630)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import BaseMessage

from soothe.foundation.sloop.intention.models import build_loop_routing_classification

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

_INTENT_CLASSIFY_STATUS_LABEL = "Interpreting goal"


def _ledger_messages_for_intake(ctx: LoopRuntimeContext) -> list[BaseMessage]:
    """Best-effort ledger tail for intake projection."""
    ce = ctx.ce
    if ce is None:
        return []
    try:
        return [msg for msg, _phase in ce.get_ledger_entries()]
    except Exception:
        logger.debug(
            "Could not read ledger entries for intake projection (loop=%s)",
            ctx.state_manager.loop_id,
            exc_info=True,
        )
        return []


def _should_skip_intent_classify(ctx: LoopRuntimeContext) -> bool:
    """True when this turn must not run intake LLM (RFC-622 clarification resume)."""
    if (ctx.clarification_resume_text or "").strip():
        return True
    if ctx.clarification_resume_answers:
        return True
    return False


async def node_intent_classify(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Classify user intake and attach routing metadata to ``ctx.loop_state``."""
    if _should_skip_intent_classify(ctx):
        logger.info("[Intent] Skipping graph entry classification (clarification resume)")
        return {}

    classifier = ctx.intent_classifier
    if classifier is None:
        logger.debug("[Intent] No classifier configured; graph will use complex fallback routing")
        return {}

    await ctx.emit("plan_phase_status", {"label": _INTENT_CLASSIFY_STATUS_LABEL})

    query = ctx.loop_state.goal_user_submission or ctx.loop_state.goal
    thread_id = ctx.loop_state.thread_id
    loop_messages = _ledger_messages_for_intake(ctx)

    intent = await classifier.classify_intake(
        query,
        loop_messages=loop_messages,
        thread_id=thread_id,
        context_engine=ctx.ce,
        goal_trace=ctx.goal_trace,
        observability_phase="strange_loop_graph",
        observability_component="strange_loop.intent_classification",
    )
    ctx.loop_state.intent = intent
    ctx.loop_state.routing_classification = build_loop_routing_classification(
        intent,
        ctx.preferred_subagent,
    )

    logger.info(
        "[Intent] Graph classified intake: intake=%s - %s",
        intent.intake_label,
        query[:50],
    )

    if intent.reasoning:
        await ctx.emit(
            "intent_classified_reasoning",
            {
                "intent_type": "agentic",
                "reasoning": intent.reasoning,
                "goal_description": intent.goal_description,
            },
        )

    return {}
