"""Loop Graph entry node: LLM intake classification (RFC-220, RFC-630, IG-554).

IG-554: Two-pass intake architecture:
- Pass 1: Social vs task (no prior context)
- Pass 2: Scope classification (with prior projection), only if is_task=True
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
from soothe.foundation.sloop.prompts.plan_ledger_projection import (
    project_last_goal_completion_for_intake,
)

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
    """Classify user intake using two-pass architecture (RFC-630 IG-554).

    Pass 1 decides social vs task; Pass 2 decides scope (trivial/simple/complex).
    Prior context is excluded from Pass 1 for clean decision boundary.
    """
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

    # IG-554: Two-pass intake
    # Check if classifier supports two-pass (has _pass1_classifier attribute)
    # Fall back to legacy classify_intake for backward compatibility
    if hasattr(classifier, "_pass1_classifier"):
        # Two-pass mode
        from soothe.foundation.sloop.intention.two_pass_coordinator import TwoPassIntakeCoordinator

        # Build prior projection for Pass 2
        ledger_cfg = None
        strange_loop = getattr(ctx, "strange_loop", None)
        if strange_loop is not None:
            config = getattr(strange_loop, "config", None)
            if config is not None and hasattr(config, "agent"):
                ledger_cfg = getattr(config.agent.loop, "plan_prompt_ledger", None)
        prior_projection_text = None
        if loop_messages:
            # Get projection text for Pass 2
            projected_messages = project_last_goal_completion_for_intake(loop_messages, ledger_cfg)
            if projected_messages:
                # Extract text from projected messages
                prior_projection_text = "\n".join(
                    getattr(msg, "content", str(msg)) for msg in projected_messages
                )

        coordinator = TwoPassIntakeCoordinator(
            fast_model=classifier._fast_model,
            soothe_config=classifier._soothe_config,
        )

        result = await coordinator.classify(
            query,
            prior_projection=prior_projection_text,
            goal_trace=ctx.goal_trace,
            observability_metadata={"thread_id": thread_id},
        )

        if result.is_social:
            # Social fast-path
            intent = IntentClassification(
                intake_label=IntakeLabel.CHITCHAT,
                reasoning=result.pass1_reasoning,
                goal_description=query,
                chitchat_response=result.social_response,
                task_complexity=classifier._fallback(query).task_complexity
                if hasattr(classifier, "_fallback")
                else None,
            )
            logger.info(
                "[Intent] Two-pass: SOCIAL (Pass1 confidence=%s) - %s",
                result.pass1_confidence,
                query[:50],
            )
        else:
            # Task - use Pass 2 result
            intent = result.intent_classification
            if intent is None:
                # Fallback to complex if Pass 2 failed
                intent = classifier._fallback(query) if hasattr(classifier, "_fallback") else None
            logger.info(
                "[Intent] Two-pass: TASK scope=%s (Pass1 confidence=%s) - %s",
                result.scope,
                result.pass1_confidence,
                query[:50],
            )
    else:
        # Legacy one-pass mode (backward compatibility)
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
            "[Intent] Legacy one-pass: intake=%s - %s",
            intent.intake_label,
            query[:50],
        )

    ctx.loop_state.intent = intent
    ctx.loop_state.routing_classification = build_loop_routing_classification(
        intent,
        ctx.preferred_subagent,
    )

    if intent.reasoning and intent.intake_label != IntakeLabel.CHITCHAT:
        await ctx.emit(
            "intent_classified_reasoning",
            {
                "intent_type": "agentic",
                "reasoning": intent.reasoning,
                "goal_description": intent.goal_description,
            },
        )

    return {}
