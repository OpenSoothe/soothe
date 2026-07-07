"""Intent classifier implementation (RFC-225, RFC-630, IG-554).

Two-pass intake classification: Pass 1 (social vs task) then Pass 2 (scope).
Loop continuation is derived structurally inside ``StrangeLoop`` from the
loaded checkpoint and is not a classifier concern.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage

from soothe.foundation.sloop.prompts.plan_ledger_projection import (
    project_last_goal_completion_for_intake,
)

from .models import (
    IntakeLabel,
    IntakePass1Confidence,
    IntakePass1LLMResult,
    IntakePass2LLMResult,
    IntentClassification,
    derive_task_complexity_from_intake,
)
from .pass1_social_response import resolve_pass1_chitchat_response
from .two_pass_coordinator import TwoPassIntakeCoordinator, TwoPassIntakeResult

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


def prior_projection_text_from_messages(
    loop_messages: list[BaseMessage] | None,
    ledger_cfg: Any | None,
) -> str | None:
    """Build prior-goal summary text for Pass 2 from ledger messages.

    IG-555: Intake Pass 2 omits boundary marker since classifier needs prior
    scope signal for reference resolution, not planning anchoring prevention.
    """
    if not loop_messages:
        return None
    projected = project_last_goal_completion_for_intake(
        loop_messages, ledger_cfg, include_boundary=False
    )
    if not projected:
        return None
    return "\n".join(getattr(msg, "content", str(msg)) for msg in projected)


class IntentClassifier:
    """Two-pass LLM intake classification (RFC-630, IG-554).

    Pass 1 decides social vs task without prior context. Pass 2 classifies
    scope (trivial/simple/complex) with prior projection when available.

    Args:
        model: Fast LLM for classification (e.g., gpt-4o-mini).
        assistant_name: Name used in intake identity block.
        soothe_config: Optional config for Langfuse tracing.
    """

    def __init__(
        self,
        model: BaseChatModel | None,
        assistant_name: str = "Soothe",
        soothe_config: SootheConfig | None = None,
    ) -> None:
        self._fast_model = model
        self._assistant_name = assistant_name
        self._soothe_config = soothe_config
        self._two_pass = TwoPassIntakeCoordinator(
            model,
            soothe_config,
            assistant_name=assistant_name,
        )
        self._pass1_classifier = self._two_pass._pass1_classifier

        if model:
            logger.info("[IntentClassifier] Initialized with two-pass intake")
        else:
            logger.warning("[IntentClassifier] No model provided, classification disabled")

    async def classify_pass1(
        self,
        query: str,
        *,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> IntakePass1LLMResult:
        """Run Pass 1 only (social vs task) for pre-graph gather."""
        result = await self._two_pass.classify_social_only(
            query,
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
        )
        return result._pass1_result  # noqa: SLF001

    async def classify_scope_intake(
        self,
        query: str,
        *,
        loop_messages: list[BaseMessage] | None = None,
        thread_id: str | None = None,
        context_engine: Any | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
        observability_phase: str = "pre-stream",
        observability_component: str = "intake.pass2",
    ) -> IntentClassification:
        """Run Pass 2 only after Pass 1 determined the query is a task."""
        if not self._fast_model:
            return self._fallback(query)

        ledger_cfg = (
            self._soothe_config.agent.loop.plan_prompt_ledger if self._soothe_config else None
        )
        prior_projection = prior_projection_text_from_messages(loop_messages, ledger_cfg)

        pass2_result = await self._two_pass.classify_scope(
            query,
            prior_projection=prior_projection,
            observability_metadata={
                **(observability_metadata or {}),
                "observability_phase": observability_phase,
                "observability_component": observability_component,
            },
            goal_trace=goal_trace,
        )
        intent = self._pass2_to_intent(pass2_result, query)
        await self._record_pass2_ledger(
            query=query,
            pass2_result=pass2_result,
            thread_id=thread_id,
            context_engine=context_engine,
        )
        return intent

    async def classify_intake(
        self,
        query: str,
        *,
        loop_messages: list[BaseMessage] | None = None,
        thread_id: str | None = None,
        context_engine: Any | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
        observability_phase: str = "strange_loop_graph",
        observability_component: str = "strange_loop.intent_classification",
    ) -> IntentClassification:
        """Classify query via two-pass intake (RFC-630, IG-554).

        Args:
            query: User input text.
            loop_messages: Optional persisted ledger for prior-goal projection.
            thread_id: Thread id for ledger metadata (optional).
            context_engine: Optional CE instance for intent-classify ledger writes.
            observability_metadata: Optional metadata for observability.
            goal_trace: Optional Langfuse trace context.
            observability_phase: Langfuse/metadata phase label.
            observability_component: Langfuse component label.

        Returns:
            IntentClassification with intake_label for routing.
        """
        if not self._fast_model:
            return self._fallback(query)

        ledger_cfg = (
            self._soothe_config.agent.loop.plan_prompt_ledger if self._soothe_config else None
        )
        prior_projection = prior_projection_text_from_messages(loop_messages, ledger_cfg)

        two_pass_result = await self._two_pass.classify(
            query,
            prior_projection=prior_projection,
            observability_metadata={
                **(observability_metadata or {}),
                "observability_phase": observability_phase,
                "observability_component": observability_component,
            },
            goal_trace=goal_trace,
        )
        intent = self._two_pass_to_intent(two_pass_result, query)

        if two_pass_result.is_task and two_pass_result._pass2_result is not None:
            await self._record_pass2_ledger(
                query=query,
                pass2_result=two_pass_result._pass2_result,
                thread_id=thread_id,
                context_engine=context_engine,
            )

        logger.debug(
            "Intake classified: intake_label=%s complexity=%s",
            intent.intake_label,
            intent.task_complexity,
        )
        return intent

    def pass1_to_intent(
        self,
        pass1_result: IntakePass1LLMResult,
        query: str,
    ) -> IntentClassification:
        """Convert Pass 1 social result to IntentClassification for fast-path."""
        response = resolve_pass1_chitchat_response(
            pass1_result,
            query=query,
        )
        return IntentClassification(
            intake_label=IntakeLabel.CHITCHAT,
            reasoning=pass1_result.reasoning,
            goal_description=query,
            chitchat_response=response,
            task_complexity=derive_task_complexity_from_intake(IntakeLabel.CHITCHAT),
        )

    def _two_pass_to_intent(
        self,
        result: TwoPassIntakeResult,
        query: str,
    ) -> IntentClassification:
        """Convert coordinator result to IntentClassification."""
        if result.is_social:
            intent = self.pass1_to_intent(result._pass1_result, query)  # noqa: SLF001
            return self._patch_missing_fields(intent, query)

        intent = result.intent_classification
        if intent is None:
            return self._fallback(query)
        return self._patch_missing_fields(intent, query)

    def _pass2_to_intent(
        self,
        pass2_result: IntakePass2LLMResult,
        query: str,
    ) -> IntentClassification:
        """Convert Pass 2 scope result to IntentClassification."""
        intake_label = pass2_result.to_intake_label()
        intent = IntentClassification(
            intake_label=intake_label,
            reasoning=pass2_result.reasoning,
            goal_description=pass2_result.goal_description,
            chitchat_response=None,
            task_complexity=derive_task_complexity_from_intake(intake_label),
        )
        return self._patch_missing_fields(intent, query)

    async def _record_pass2_ledger(
        self,
        *,
        query: str,
        pass2_result: IntakePass2LLMResult,
        thread_id: str | None,
        context_engine: Any | None,
    ) -> None:
        """Append Pass 2 intake pair to the CE ledger when CE is available."""
        if context_engine is None:
            return
        from soothe.foundation.sloop.cognition.ledger_compaction import (
            compact_planning_human_content,
        )
        from soothe.foundation.sloop.utils.messages import (
            LoopAIMessage,
            LoopHumanMessage,
            _record_ledger_message,
        )

        human_content = f"GOAL:\n{query}\n\nTASK:\nClassify scope."
        llm_dict = pass2_result.model_dump()
        tid = (thread_id or "").strip()
        human_msg = LoopHumanMessage(
            content=compact_planning_human_content(human_content),
            thread_id=tid or None,
            iteration=0,
            phase="intent_classify",
        )
        ai_msg = LoopAIMessage(
            content=json.dumps(llm_dict, ensure_ascii=False),
            thread_id=tid or None,
            iteration=0,
            phase="intent_classify",
        )
        try:
            _record_ledger_message(context_engine, human_msg, "intent_classify")
            _record_ledger_message(context_engine, ai_msg, "intent_classify")
            await context_engine.save()
        except Exception:
            logger.warning("Failed to record Pass 2 intent-classify ledger pair", exc_info=True)

    def _fallback(
        self,
        query: str,
        *,
        error_context: Exception | None = None,
    ) -> IntentClassification:
        """Safe fallback to ``complex`` (RFC-630): run the full pipeline."""
        reason = type(error_context).__name__ if error_context else "classification_disabled"
        logger.debug("Intake fallback to complex (%s)", reason)
        return IntentClassification(
            intake_label=IntakeLabel.COMPLEX,
            reasoning="Let me run the full agent loop to work through this goal.",
            goal_description=query,
            task_complexity=derive_task_complexity_from_intake(IntakeLabel.COMPLEX),
        )

    def _patch_missing_fields(
        self,
        intent: IntentClassification,
        query: str,
    ) -> IntentClassification:
        """Patch missing goal_description and reasoning."""
        if not intent.goal_description:
            intent.goal_description = query
            logger.debug("Patched missing goal_description")
        if intent.intake_label == IntakeLabel.CHITCHAT:
            if not (intent.chitchat_response or "").strip():
                intent.chitchat_response = resolve_pass1_chitchat_response(
                    IntakePass1LLMResult(
                        is_task=False,
                        confidence=IntakePass1Confidence.HIGH,
                        social_response=None,
                        reasoning=intent.reasoning or "",
                    ),
                    query=query,
                )
                logger.debug("Patched missing chitchat_response")
            return intent
        if not intent.reasoning:
            intent.reasoning = "I'll use tools to work through this goal."
            logger.debug("Patched missing reasoning")
        return intent


__all__ = ["IntentClassifier", "prior_projection_text_from_messages"]
