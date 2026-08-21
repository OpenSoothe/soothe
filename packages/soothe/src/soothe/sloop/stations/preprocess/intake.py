"""Loop Graph entry node: LLM intake classification (RFC-220, RFC-630).

This node is the sole intake classification call site. It projects the CE
ledger (prior-goal completion + preamble) into the classify LLM. When
``loop_state.intent`` is already set (client-forced ``intake_scope`` or
clarification resume), the classify call is skipped.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    build_loop_routing_classification,
    normalize_response_language,
)
from soothe.sloop.orchestrator.phase_status import emit_plan_phase_status
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

INTENT_CLASSIFY_STATUS_LABEL = "Interpreting goal"


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
    """True when intake reasoning is non-empty user-facing prose for TUI cards."""
    return bool((text or "").strip())


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
) -> list[tuple[str, dict[str, Any]]]:
    """Build zero or one intake cognition card (task reasoning only).

    Skips chitchat.
    """
    if intent.intake_label == IntakeLabel.CHITCHAT:
        return []
    reasoning_event = intake_reasoning_event((intent.reasoning or "").strip())
    if reasoning_event is None:
        return []
    return [reasoning_event]


def _ledger_messages_for_intake(ctx: LoopRuntimeContext) -> list[BaseMessage]:
    """Best-effort phase-tagged ledger messages for intake projection."""
    try:
        return list(ctx.loop_state.loop_messages)
    except Exception:
        logger.debug(
            "Could not read ledger messages for intake projection (loop=%s)",
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


async def node_intent_classify(
    ctx: LoopRuntimeContext,
    _state: dict[str, Any],
    runnable_config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Classify user intake with ledger projection (RFC-630)."""
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
    loop_messages = _ledger_messages_for_intake(ctx)

    prior_language = normalize_response_language(getattr(ctx.loop_state, "response_language", None))

    intent = await classifier.classify_intake(
        query,
        loop_messages=loop_messages,
        prior_response_language=prior_language,
        goal_trace=ctx.goal_trace,
        parent_runnable_config=dict(runnable_config) if runnable_config is not None else None,
    )

    await emit_plan_phase_status(ctx, label=INTENT_CLASSIFY_STATUS_LABEL)

    logger.info(
        "[Intent] Intake: loop_id=%s intake=%s query=%s",
        ctx.state_manager.loop_id,
        intent.intake_label,
        query[:50],
    )

    _apply_intent_to_loop_state(ctx.loop_state, intent, preferred_subagent=ctx.preferred_subagent)

    for event_type, payload in intent_pass_reasoning_events(intent):
        await ctx.emit(event_type, payload)

    return {}
