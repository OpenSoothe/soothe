"""Intake coordinator: orchestrates social-vs-task and full classification."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage

from .intake_classifier import IntakeClassifier, build_intake_task_fallback
from .models import (
    IntakeConfidence,
    IntakeLabel,
    IntakeLLMResult,
    IntentClassification,
    ResponseLanguage,
    intent_classification_from_intake,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig
    from soothe.config.models import AssistantIdentity

logger = logging.getLogger(__name__)


class IntakeResult:
    """Result from intake classification.

    Either:
    - is_task=False with social_response (chitchat fast-path)
    - is_task=True with IntentClassification (agentic path)
    """

    __slots__ = (
        "_is_task",
        "_intake_result",
        "_intent_classification",
    )

    def __init__(self, intake_result: IntakeLLMResult) -> None:
        self._is_task = intake_result.is_task
        self._intake_result = intake_result

        if intake_result.is_task:
            self._intent_classification = intent_classification_from_intake(intake_result)
        else:
            self._intent_classification = None

    @property
    def is_task(self) -> bool:
        """True if this is a work request; False if social."""
        return self._is_task

    @property
    def is_social(self) -> bool:
        """True if this is a social interaction (greeting, thanks, etc)."""
        return not self._is_task

    @property
    def social_response(self) -> str | None:
        """Direct response for social queries (is_task=False)."""
        if self._is_task:
            return None
        return self._intake_result.social_response

    @property
    def intake_label(self) -> IntakeLabel | None:
        """Final intake label (chitchat, or derived from task complexity)."""
        if not self._is_task:
            return IntakeLabel.CHITCHAT
        intent = self._intent_classification
        if intent is None:
            return IntakeLabel.COMPLEX
        return intent.intake_label

    @property
    def intent_classification(self) -> IntentClassification | None:
        """IntentClassification for passing to StrangeLoop (task queries only)."""
        return self._intent_classification


class IntakeCoordinator:
    """Orchestrates intake classification (social vs task + task complexity).

    Args:
        fast_model: Fast LLM for intake classification.
        soothe_config: Optional config for rate limiting and tracing.
    """

    def __init__(
        self,
        fast_model: BaseChatModel | None,
        soothe_config: SootheConfig | None = None,
        *,
        assistant_name: str = "Soothe",
        assistant_identity: AssistantIdentity | None = None,
    ) -> None:
        self._intake_classifier = IntakeClassifier(
            fast_model,
            soothe_config,
            assistant_name=assistant_name,
            assistant_identity=assistant_identity,
        )
        self._soothe_config = soothe_config

        if fast_model:
            logger.debug("[Intake] Initialized")
        else:
            logger.warning("[Intake] No model, intake disabled")

    async def classify(
        self,
        query: str,
        *,
        ledger_messages: list[BaseMessage] | None = None,
        prior_response_language: ResponseLanguage | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
        parent_runnable_config: dict[str, Any] | None = None,
    ) -> IntakeResult:
        """Run full intake classification (with ledger context when provided)."""
        intake_result = await self._intake_classifier.classify(
            query,
            ledger_messages=ledger_messages,
            prior_response_language=prior_response_language,
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
            parent_runnable_config=parent_runnable_config,
        )
        intake_result = _apply_low_confidence_fail_safe(intake_result)

        logger.debug(
            "Intake result: is_task=%s confidence=%s",
            intake_result.is_task,
            intake_result.confidence,
        )

        if not intake_result.is_task:
            logger.info(
                "Intake: SOCIAL (confidence=%s) - %s",
                intake_result.confidence,
                query[:50],
            )
            return IntakeResult(intake_result)

        logger.info(
            "Intake: TASK (confidence=%s) - %s",
            intake_result.confidence,
            query[:50],
        )
        return IntakeResult(intake_result)


def _apply_low_confidence_fail_safe(intake_result: IntakeLLMResult) -> IntakeLLMResult:
    """Low-confidence social verdicts fail-safe to task."""
    if not intake_result.is_task and intake_result.confidence == IntakeConfidence.LOW:
        logger.info("Low-confidence social verdict overridden to task (fail-safe)")
        return build_intake_task_fallback(response_language=intake_result.response_language)
    return intake_result


__all__ = ["IntakeCoordinator", "IntakeResult"]
