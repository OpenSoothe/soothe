"""Two-pass intake coordinator (RFC-630 IG-554).

Orchestrates Pass 1 (social vs task) and Pass 2 (scope) classification.
Pass 1 runs first; if social, returns immediately without Pass 2.
If task, Pass 2 runs with prior projection for scope classification.
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
    derive_task_complexity_from_intake,
)
from .pass1_classifier import IntakePass1Classifier
from .pass2_classifier import IntakePass2Classifier

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class TwoPassIntakeResult:
    """Result from two-pass intake classification.

    Either:
    - is_task=False with social_response (chitchat fast-path)
    - is_task=True with scope and IntentClassification (agentic path)
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

        # Build IntentClassification if task
        if pass1_result.is_task and pass2_result is not None:
            intake_label = pass2_result.to_intake_label()
            self._intent_classification = IntentClassification(
                intake_label=intake_label,
                reasoning=pass2_result.reasoning,
                pass1_reasoning=pass1_result.reasoning,
                chitchat_response=None,
                multi_phase=pass2_result.multi_phase,
                wire_subagent=pass2_result.wire_subagent,
                requires_tool_use=pass2_result.requires_tool_use,
                response_language=pass1_result.response_language,
                task_complexity=derive_task_complexity_from_intake(intake_label),
            )
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
        """Scope classification (trivial/simple/complex) for task queries."""
        if not self._is_task or self._pass2_result is None:
            return None
        return self._pass2_result.scope

    @property
    def intake_label(self) -> IntakeLabel | None:
        """Final intake label (chitchat/trivial/simple/complex)."""
        if not self._is_task:
            return IntakeLabel.CHITCHAT
        if self._pass2_result is None:
            return None
        return self._pass2_result.to_intake_label()

    @property
    def intent_classification(self) -> IntentClassification | None:
        """IntentClassification for passing to StrangeLoop (task queries only)."""
        return self._intent_classification

    @property
    def pass1_confidence(self) -> str:
        """Pass 1 confidence level."""
        return self._pass1_result.confidence

    @property
    def pass1_reasoning(self) -> str:
        """Pass 1 reasoning."""
        return self._pass1_result.reasoning


class TwoPassIntakeCoordinator:
    """Orchestrates two-pass intake classification (RFC-630 IG-554).

    Pass 1: Social vs task (no prior context).
    Pass 2: Scope classification (with prior projection), only if is_task=True.

    Args:
        fast_model: Fast LLM for both passes.
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
        self._pass2_classifier = IntakePass2Classifier(fast_model, soothe_config)
        self._soothe_config = soothe_config

        if fast_model:
            logger.debug("[TwoPassIntake] Initialized")
        else:
            logger.warning("[TwoPassIntake] No model, intake disabled")

    async def classify(
        self,
        query: str,
        *,
        prior_projection: str | None = None,
        prior_response_language: ResponseLanguage | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> TwoPassIntakeResult:
        """Run two-pass intake classification.

        Pass 1 runs first. If is_task=False, returns immediately with social_response.
        If is_task=True, runs Pass 2 with prior projection for scope classification.

        Args:
            query: User input text.
            prior_projection: Prior-goal summary for Pass 2 (reference resolution).
            observability_metadata: Optional metadata for observability.
            goal_trace: Optional Langfuse trace context.

        Returns:
            TwoPassIntakeResult with either social_response or intent_classification.
        """
        # Pass 1: social vs task
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

        # If social, return immediately (no Pass 2)
        if not pass1_result.is_task:
            logger.info(
                "Two-pass intake: SOCIAL (confidence=%s) - %s",
                pass1_result.confidence,
                query[:50],
            )
            return TwoPassIntakeResult(pass1_result)

        # Pass 2: scope classification (with prior projection)
        pass2_result = await self._pass2_classifier.classify(
            query,
            prior_projection=prior_projection,
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
        )

        logger.info(
            "Two-pass intake: TASK scope=%s confidence=%s - %s",
            pass2_result.scope,
            pass1_result.confidence,
            query[:50],
        )

        return TwoPassIntakeResult(pass1_result, pass2_result)

    async def classify_social_only(
        self,
        query: str,
        *,
        prior_response_language: ResponseLanguage | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> TwoPassIntakeResult:
        """Run Pass 1 only (for pre-graph fast-path decision).

        Use when you need to decide whether to enter the graph at all,
        before checkpoint is loaded. If is_task=True, the caller should
        load checkpoint and run Pass 2 separately.

        Args:
            query: User input text.
            observability_metadata: Optional metadata for observability.
            goal_trace: Optional Langfuse trace context.

        Returns:
            TwoPassIntakeResult (Pass 2 will be None if is_task=True).
        """
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

        logger.debug(
            "Pass1-only: TASK (needs Pass 2) - %s",
            query[:50],
        )
        # Return with pass2=None; caller will run Pass 2 after checkpoint load
        return TwoPassIntakeResult(pass1_result)

    async def classify_scope(
        self,
        query: str,
        *,
        prior_projection: str | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> IntakePass2LLMResult:
        """Run Pass 2 only (when Pass 1 already determined is_task=True).

        Args:
            query: User input text.
            prior_projection: Prior-goal summary for reference resolution.
            observability_metadata: Optional metadata for observability.
            goal_trace: Optional Langfuse trace context.

        Returns:
            IntakePass2LLMResult with scope classification.
        """
        return await self._pass2_classifier.classify(
            query,
            prior_projection=prior_projection,
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
        )


def _apply_low_confidence_fail_safe(pass1_result: IntakePass1LLMResult) -> IntakePass1LLMResult:
    """Low-confidence social verdicts fail-safe to task (Pass 2 runs)."""
    if not pass1_result.is_task and pass1_result.confidence == IntakePass1Confidence.LOW:
        logger.info("Pass1 low-confidence social verdict overridden to task (fail-safe)")
        return pass1_result.model_copy(
            update={
                "is_task": True,
                "social_response": None,
                "reasoning": "Low confidence fail-safe to task",
            }
        )
    return pass1_result


__all__ = [
    "TwoPassIntakeCoordinator",
    "TwoPassIntakeResult",
]
