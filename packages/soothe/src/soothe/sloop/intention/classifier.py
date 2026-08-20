"""Intent classifier facade (RFC-225, RFC-630, RFC-904).

Intake classification decides social vs task, and for tasks emits
``task_complexity`` and a short step-card title. Loop continuation is derived
structurally inside ``StrangeLoop`` from the loaded checkpoint.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .chitchat_fallbacks import pick_generic_chitchat_fallback
from .coordinator import IntakeCoordinator, IntakeResult
from .models import (
    IntakeLabel,
    IntakeLLMResult,
    IntentClassification,
    ResponseLanguage,
    derive_task_complexity_from_intake,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class IntentClassifier:
    """Intake classification facade.

    Two entry points:
    - ``classify_social_gate``: context-free social-vs-task gate (pre-graph).
    - ``classify_intake``: full classification with ledger projection (post-CE).

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
        self._coordinator = IntakeCoordinator(
            model,
            soothe_config,
            assistant_name=assistant_name,
        )
        self._intake_classifier = self._coordinator._intake_classifier

        if model:
            logger.info("[IntentClassifier] Initialized with intake classification")
        else:
            logger.warning("[IntentClassifier] No model provided, classification disabled")

    async def classify_social_gate(
        self,
        query: str,
        *,
        prior_response_language: ResponseLanguage | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> IntakeLLMResult:
        """Run the social-vs-task gate (context-free) for the pre-graph fast path."""
        result = await self._coordinator.classify_social_gate(
            query,
            prior_response_language=prior_response_language,
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
        )
        return result._intake_result  # noqa: SLF001

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
        parent_runnable_config: dict[str, Any] | None = None,
    ) -> IntentClassification:
        """Classify query via full intake classification (with ledger context).

        Projects prior-goal completion units from the ledger into the prompt so
        the classifier can reason about context and emit ``task_complexity`` /
        ``task_short_description``.
        """
        del thread_id, context_engine
        if not self._fast_model:
            return self._fallback(query)

        ledger_messages = self._project_ledger_for_intake(loop_messages)

        intake_result = await self._coordinator.classify(
            query,
            ledger_messages=ledger_messages,
            prior_response_language=prior_response_language,
            observability_metadata={
                **(observability_metadata or {}),
                "observability_phase": observability_phase,
                "observability_component": observability_component,
            },
            goal_trace=goal_trace,
            parent_runnable_config=parent_runnable_config,
        )
        intent = self._intake_to_intent(intake_result, query)

        logger.debug(
            "Intake classified: intake_label=%s complexity=%s",
            intent.intake_label,
            intent.task_complexity,
        )
        return intent

    def _project_ledger_for_intake(self, loop_messages: Any | None) -> list[Any] | None:
        """Project preamble + prior-goal completion units for intake classification."""
        if not loop_messages:
            return None
        try:
            from soothe.sloop.context_projection import LoopContextProjector, ProjectionSpec

            projector = LoopContextProjector(self._soothe_config)
            projected = projector.project(
                loop_messages,
                ProjectionSpec(phase="intake"),
            )
            return projected.messages or None
        except Exception:
            logger.debug(
                "Intake ledger projection failed; classifying without history", exc_info=True
            )
            return None

    def intake_to_intent(
        self,
        intake_result: IntakeLLMResult,
        query: str,
    ) -> IntentClassification:
        """Convert an intake task result to IntentClassification."""
        from soothe.sloop.intention.models import intent_classification_from_intake

        return self._patch_missing_fields(
            intent_classification_from_intake(intake_result),
            query,
        )

    def social_to_intent(
        self,
        intake_result: IntakeLLMResult,
        query: str,
    ) -> IntentClassification:
        """Convert an intake social result to IntentClassification for the fast path."""
        return IntentClassification(
            intake_label=IntakeLabel.CHITCHAT,
            reasoning=intake_result.reasoning,
            chitchat_response=(intake_result.social_response or "").strip(),
            response_language=intake_result.response_language,
            task_complexity=derive_task_complexity_from_intake(IntakeLabel.CHITCHAT),
        )

    def _intake_to_intent(
        self,
        result: IntakeResult,
        query: str,
    ) -> IntentClassification:
        """Convert a coordinator result to IntentClassification."""
        if result.is_social:
            intent = self.social_to_intent(result._intake_result, query)  # noqa: SLF001
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
        """Safe fallback to ``complex``: run the full pipeline."""
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
