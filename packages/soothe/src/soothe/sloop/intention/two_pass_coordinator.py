"""Pass1-only intake coordinator (RFC-630 pass1 + RFC-904).

Orchestrates Pass 1 (social vs task). Pass 2 scope classification is removed;
tasks enter do-or-decompose without trivial/simple/complex pre-routing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .models import (
    IntakeLabel,
    IntakePass1Confidence,
    IntakePass1LLMResult,
    IntakePass2LLMResult,
    IntakeScope,
    IntentClassification,
    ResponseLanguage,
    intent_classification_from_pass1_task,
    intent_classification_from_pass2,
)
from .pass1_classifier import IntakePass1Classifier, build_pass1_task_fallback

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class TwoPassIntakeResult:
    """Result from Pass 1 intake classification.

    Either:
    - is_task=False with social_response (chitchat fast-path)
    - is_task=True with IntentClassification (agentic path; no Pass 2)
    """

    __slots__ = (
        "_is_task",
        "_pass1_result",
        "_pass2_result",
        "_intent_classification",
    )

    def __init__(
        self,
        pass1_result: IntakePass1LLMResult,
        pass2_result: IntakePass2LLMResult | None = None,
    ) -> None:
        self._is_task = pass1_result.is_task
        self._pass1_result = pass1_result
        self._pass2_result = pass2_result

        if pass1_result.is_task and pass2_result is not None:
            self._intent_classification = intent_classification_from_pass2(
                pass2_result,
                response_language=pass1_result.response_language,
            )
        elif pass1_result.is_task:
            self._intent_classification = intent_classification_from_pass1_task(pass1_result)
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
        return self._pass1_result.social_response

    @property
    def scope(self) -> IntakeScope | None:
        """Legacy scope field; None when Pass 2 is not used."""
        if not self._is_task or self._pass2_result is None:
            return None
        return self._pass2_result.scope

    @property
    def intake_label(self) -> IntakeLabel | None:
        """Final intake label (chitchat or task→complex compatibility)."""
        if not self._is_task:
            return IntakeLabel.CHITCHAT
        if self._pass2_result is None:
            return IntakeLabel.COMPLEX
        return self._pass2_result.to_intake_label()

    @property
    def intent_classification(self) -> IntentClassification | None:
        """IntentClassification for passing to StrangeLoop (task queries only)."""
        return self._intent_classification

    @property
    def pass1_confidence(self) -> str:
        """Pass 1 confidence level."""
        return self._pass1_result.confidence


class TwoPassIntakeCoordinator:
    """Orchestrates Pass 1 intake classification (RFC-630 / RFC-904).

    Pass 1: Social vs task (no prior context). Tasks skip Pass 2.

    Args:
        fast_model: Fast LLM for Pass 1.
        soothe_config: Optional config for rate limiting and tracing.
    """

    def __init__(
        self,
        fast_model: BaseChatModel | None,
        soothe_config: SootheConfig | None = None,
        *,
        assistant_name: str = "Soothe",
    ) -> None:
        self._pass1_classifier = IntakePass1Classifier(
            fast_model,
            soothe_config,
            assistant_name=assistant_name,
        )
        self._soothe_config = soothe_config

        if fast_model:
            logger.debug("[Pass1Intake] Initialized")
        else:
            logger.warning("[Pass1Intake] No model, intake disabled")

    async def classify(
        self,
        query: str,
        *,
        prior_projection: str | None = None,
        prior_response_language: ResponseLanguage | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> TwoPassIntakeResult:
        """Run Pass 1 intake classification (RFC-904: no Pass 2)."""
        del prior_projection  # unused after Pass 2 removal
        pass1_result = await self._pass1_classifier.classify(
            query,
            prior_response_language=prior_response_language,
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
        )
        pass1_result = _apply_low_confidence_fail_safe(pass1_result)

        logger.debug(
            "Pass1 result: is_task=%s confidence=%s",
            pass1_result.is_task,
            pass1_result.confidence,
        )

        if not pass1_result.is_task:
            logger.info(
                "Pass1 intake: SOCIAL (confidence=%s) - %s",
                pass1_result.confidence,
                query[:50],
            )
            return TwoPassIntakeResult(pass1_result)

        logger.info(
            "Pass1 intake: TASK (confidence=%s) - %s",
            pass1_result.confidence,
            query[:50],
        )
        return TwoPassIntakeResult(pass1_result)

    async def classify_social_only(
        self,
        query: str,
        *,
        prior_response_language: ResponseLanguage | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> TwoPassIntakeResult:
        """Run Pass 1 only (pre-graph fast-path). Tasks return without Pass 2."""
        pass1_result = await self._pass1_classifier.classify(
            query,
            prior_response_language=prior_response_language,
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
        )
        pass1_result = _apply_low_confidence_fail_safe(pass1_result)

        if not pass1_result.is_task:
            logger.info(
                "Pass1-only: SOCIAL (confidence=%s) - %s",
                pass1_result.confidence,
                query[:50],
            )
            return TwoPassIntakeResult(pass1_result)

        logger.debug("Pass1-only: TASK - %s", query[:50])
        return TwoPassIntakeResult(pass1_result)


def _apply_low_confidence_fail_safe(pass1_result: IntakePass1LLMResult) -> IntakePass1LLMResult:
    """Low-confidence social verdicts fail-safe to task."""
    if not pass1_result.is_task and pass1_result.confidence == IntakePass1Confidence.LOW:
        logger.info("Pass1 low-confidence social verdict overridden to task (fail-safe)")
        return build_pass1_task_fallback(response_language=pass1_result.response_language)
    return pass1_result


__all__ = ["TwoPassIntakeCoordinator", "TwoPassIntakeResult"]
