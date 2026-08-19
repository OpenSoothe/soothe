"""Intent classifier implementation (RFC-225, RFC-630 pass1, RFC-904).

Pass 1 decides social vs task. Pass 2 scope classification is removed;
tasks enter do-or-decompose. Loop continuation is derived structurally inside
``StrangeLoop`` from the loaded checkpoint.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .chitchat_fallbacks import pick_generic_chitchat_fallback
from .models import (
    IntakeLabel,
    IntakePass1LLMResult,
    IntentClassification,
    ResponseLanguage,
    derive_task_complexity_from_intake,
)
from .two_pass_coordinator import TwoPassIntakeCoordinator, TwoPassIntakeResult

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class IntentClassifier:
    """Pass 1 LLM intake classification (RFC-630 / RFC-904).

    Pass 1 decides social vs task without prior context. Tasks skip Pass 2.

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
            logger.info("[IntentClassifier] Initialized with pass1 intake")
        else:
            logger.warning("[IntentClassifier] No model provided, classification disabled")

    async def classify_pass1(
        self,
        query: str,
        *,
        prior_response_language: ResponseLanguage | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> IntakePass1LLMResult:
        """Run Pass 1 only (social vs task) for pre-graph gather."""
        result = await self._two_pass.classify_social_only(
            query,
            prior_response_language=prior_response_language,
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
        )
        return result._pass1_result  # noqa: SLF001

    async def classify_scope_intake(
        self,
        query: str,
        *,
        loop_messages: Any | None = None,
        thread_id: str | None = None,
        context_engine: Any | None = None,
        pass1_response_language: ResponseLanguage | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
        observability_phase: str = "pre-stream",
        observability_component: str = "intake.pass1",
    ) -> IntentClassification:
        """Legacy name: build task intent without Pass 2 (RFC-904)."""
        del loop_messages, thread_id, context_engine, observability_metadata
        del goal_trace, observability_phase, observability_component
        if not self._fast_model:
            return self._fallback(query)
        from soothe.sloop.intention.models import intent_classification_from_pass1_task
        from soothe.sloop.intention.pass1_classifier import build_pass1_task_fallback

        pass1 = build_pass1_task_fallback(response_language=pass1_response_language)
        return self._patch_missing_fields(intent_classification_from_pass1_task(pass1), query)

    async def classify_intake(
        self,
        query: str,
        *,
        loop_messages: Any | None = None,
        thread_id: str | None = None,
        context_engine: Any | None = None,
        prior_response_language: ResponseLanguage | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
        observability_phase: str = "strange_loop_graph",
        observability_component: str = "strange_loop.intent_classification",
    ) -> IntentClassification:
        """Classify query via Pass 1 intake (RFC-904: no Pass 2 scope)."""
        del loop_messages, thread_id, context_engine
        if not self._fast_model:
            return self._fallback(query)

        two_pass_result = await self._two_pass.classify(
            query,
            prior_response_language=prior_response_language,
            observability_metadata={
                **(observability_metadata or {}),
                "observability_phase": observability_phase,
                "observability_component": observability_component,
            },
            goal_trace=goal_trace,
        )
        intent = self._two_pass_to_intent(two_pass_result, query)

        logger.debug(
            "Intake classified: intake_label=%s complexity=%s",
            intent.intake_label,
            intent.task_complexity,
        )
        return intent

    def pass1_task_to_intent(
        self,
        pass1_result: IntakePass1LLMResult,
        query: str,
    ) -> IntentClassification:
        """Convert Pass 1 task result to IntentClassification (no Pass 2)."""
        from soothe.sloop.intention.models import intent_classification_from_pass1_task

        return self._patch_missing_fields(
            intent_classification_from_pass1_task(pass1_result),
            query,
        )

    def pass1_to_intent(
        self,
        pass1_result: IntakePass1LLMResult,
        query: str,
    ) -> IntentClassification:
        """Convert Pass 1 social result to IntentClassification for fast-path."""
        return IntentClassification(
            intake_label=IntakeLabel.CHITCHAT,
            reasoning=pass1_result.reasoning,
            chitchat_response=(pass1_result.social_response or "").strip(),
            social_kind=pass1_result.social_kind,
            response_language=pass1_result.response_language,
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
            task_complexity=derive_task_complexity_from_intake(IntakeLabel.COMPLEX),
        )

    def _patch_missing_fields(
        self,
        intent: IntentClassification,
        query: str,
    ) -> IntentClassification:
        """Patch missing reasoning and chitchat fields."""
        _ = query
        if intent.intake_label == IntakeLabel.CHITCHAT:
            if not (intent.chitchat_response or "").strip():
                intent.chitchat_response = pick_generic_chitchat_fallback(intent.response_language)
                logger.debug("Patched missing chitchat_response")
            return intent
        if not intent.reasoning:
            intent.reasoning = "I'll use tools to work through this goal."
            logger.debug("Patched missing reasoning")
        return intent


__all__ = ["IntentClassifier"]
