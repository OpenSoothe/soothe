"""Loop Graph entry node: LLM intake classification (RFC-220, RFC-630, IG-554).

When intake was not pre-classified in the pre-graph gather, this node runs
the two-pass coordinator. Pre-classified intents (Pass 1 social early-exit
handled in StrangeLoop; Pass 2 after CE load) skip LLM calls here.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import BaseMessage

from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    build_loop_routing_classification,
    normalize_response_language,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.stages.plan.phase_status import emit_plan_phase_status

logger = logging.getLogger(__name__)

INTENT_CLASSIFY_STATUS_LABEL = "Interpreting goal"

# Structural fail-safe / bypass strings — not LLM prose for CognitionReasonMessage.
_NON_DISPLAYABLE_INTAKE_REASONING_PREFIXES: tuple[str, ...] = (
    "Pre-graph Pass1 error fail-safe",
    "Loop-control phrase;",
)


def _apply_intent_to_loop_state(
    loop_state: Any,
    intent: IntentClassification,
    *,
    preferred_subagent: str | None,
) -> None:
    """Persist intake classification and derived routing on loop state."""
    loop_state.intent = intent
    loop_state.response_language = normalize_response_language(intent.response_language)
    loop_state.routing_classification = build_loop_routing_classification(
        intent,
        preferred_subagent,
    )


def is_displayable_intake_reasoning(text: str) -> bool:
    """True when intake reasoning is user-facing LLM prose for TUI cards."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    return not any(stripped.startswith(p) for p in _NON_DISPLAYABLE_INTAKE_REASONING_PREFIXES)


def intake_reasoning_event(reasoning: str) -> tuple[str, dict[str, Any]] | None:
    """Build a TUI cognition-reason payload for displayable intake reasoning.

    The runner maps ``intent_classified_reasoning`` → ``IntentClassifiedEvent`` →
    ``CognitionReasonMessage``.
    """
    text = (reasoning or "").strip()
    if not is_displayable_intake_reasoning(text):
        return None
    return (
        "intent_classified_reasoning",
        {
            "intent_type": "agentic",
            "reasoning": text,
        },
    )


def intent_pass_reasoning_events(
    intent: IntentClassification,
    *,
    pass1_reasoning: str = "",
) -> list[tuple[str, dict[str, Any]]]:
    """Build zero, one, or two intake cognition cards (Pass 1 then Pass 2).

    Skips chitchat. Dedupes when Pass 2 text matches Pass 1.
    """
    if intent.intake_label == IntakeLabel.CHITCHAT:
        return []
    events: list[tuple[str, dict[str, Any]]] = []
    pass1_event = intake_reasoning_event(pass1_reasoning or intent.pass1_reasoning or "")
    if pass1_event is not None:
        events.append(pass1_event)
    pass2_text = (intent.reasoning or "").strip()
    pass2_event = intake_reasoning_event(pass2_text)
    if pass2_event is None:
        return events
    if pass1_event is not None and pass2_event[1]["reasoning"] == pass1_event[1]["reasoning"]:
        return events
    events.append(pass2_event)
    return events


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
            _apply_intent_to_loop_state(
                ctx.loop_state,
                ctx.loop_state.intent,
                preferred_subagent=ctx.preferred_subagent,
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

    await emit_plan_phase_status(ctx, label=INTENT_CLASSIFY_STATUS_LABEL)

    query = ctx.loop_state.goal_user_submission or ctx.loop_state.goal
    thread_id = ctx.loop_state.thread_id
    loop_messages = _ledger_messages_for_intake(ctx)

    prior_language = normalize_response_language(getattr(ctx.loop_state, "response_language", None))

    intent = await classifier.classify_intake(
        query,
        loop_messages=loop_messages,
        thread_id=thread_id,
        context_engine=ctx.ce,
        prior_response_language=prior_language,
        goal_trace=ctx.goal_trace,
        observability_phase="strange_loop_graph",
        observability_component="strange_loop.intent_classification",
    )

    await emit_plan_phase_status(ctx, label=INTENT_CLASSIFY_STATUS_LABEL)

    logger.info(
        "[Intent] Two-pass: intake=%s - %s",
        intent.intake_label,
        query[:50],
    )

    _apply_intent_to_loop_state(ctx.loop_state, intent, preferred_subagent=ctx.preferred_subagent)

    for event_type, payload in intent_pass_reasoning_events(intent):
        await ctx.emit(event_type, payload)

    return {}
