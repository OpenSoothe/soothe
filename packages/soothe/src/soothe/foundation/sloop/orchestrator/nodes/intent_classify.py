"""Loop Graph entry node: LLM intake classification (RFC-220, RFC-630, IG-554).

When intake was not pre-classified in the pre-graph gather, this node runs
the two-pass coordinator. Pre-classified intents (Pass 1 social early-exit
handled in StrangeLoop; Pass 2 after CE load) skip LLM calls here.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import BaseMessage

from soothe.foundation.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    build_loop_routing_classification,
)

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

INTENT_CLASSIFY_STATUS_LABEL = "Interpreting goal"


def intent_classified_reasoning_event(
    intent: IntentClassification,
    *,
    pass1_reasoning: str = "",
) -> tuple[str, dict[str, Any]] | None:
    """Build one intake reasoning event for TUI cognition cards (IG-518, IG-554).

    Prefers Pass 2 ``intent.reasoning``; falls back to Pass 1 when Pass 2 is empty.
    """
    if intent.intake_label == IntakeLabel.CHITCHAT:
        return None
    reasoning = (intent.reasoning or pass1_reasoning or "").strip()
    if not reasoning:
        return None
    return (
        "intent_classified_reasoning",
        {
            "intent_type": "agentic",
            "reasoning": reasoning,
            "goal_description": intent.goal_description,
        },
    )


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
    """Classify user intake using two-pass architecture (RFC-630 IG-554)."""
    if _should_skip_intent_classify(ctx):
        logger.info("[Intent] Skipping graph entry classification (clarification resume)")
        return {}

    if ctx.loop_state.intent is not None:
        if ctx.loop_state.routing_classification is None:
            ctx.loop_state.routing_classification = build_loop_routing_classification(
                ctx.loop_state.intent,
                ctx.preferred_subagent,
            )
        logger.info(
            "[Intent] Skipping graph entry classification (pre-classified: %s)",
            getattr(ctx.loop_state.intent, "intake_label", "unknown"),
        )
        return {}

    classifier = ctx.intent_classifier
    if classifier is None:
        logger.debug("[Intent] No classifier configured; graph will use complex fallback routing")
        return {}

    await ctx.emit("plan_phase_status", {"label": INTENT_CLASSIFY_STATUS_LABEL})

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

    logger.info(
        "[Intent] Two-pass: intake=%s - %s",
        intent.intake_label,
        query[:50],
    )

    ctx.loop_state.intent = intent
    ctx.loop_state.routing_classification = build_loop_routing_classification(
        intent,
        ctx.preferred_subagent,
    )

    reasoning_event = intent_classified_reasoning_event(intent)
    if reasoning_event is not None:
        event_type, payload = reasoning_event
        await ctx.emit(event_type, payload)

    return {}
