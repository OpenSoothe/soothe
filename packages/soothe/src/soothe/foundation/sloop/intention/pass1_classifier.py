"""Pass 1 classifier: social vs task (RFC-630 IG-554).

Binary decision with no prior context. Returns ``is_task`` boolean plus
``social_response`` for fast-path END when social.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage

from soothe.utils.llm.invoke_policy import (
    await_with_llm_call_policy,
    llm_rate_limit_config_from,
)
from soothe.utils.llm.structured import invoke_structured_chat

from .models import IntakePass1Confidence, IntakePass1LLMResult
from .prompts import INTAKE_PASS1_HUMAN_TASK, INTAKE_PASS1_SYSTEM_PROMPT

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class IntakePass1Classifier:
    """Pass 1: binary social vs task classification (RFC-630 IG-554).

    Clean decision boundary with no prior context projection. Returns ``is_task``
    boolean and ``social_response`` for fast-path END on social queries.

    Args:
        model: Fast LLM for classification.
        soothe_config: Optional config for rate limiting and tracing.
    """

    def __init__(
        self,
        model: BaseChatModel | None,
        soothe_config: SootheConfig | None = None,
    ) -> None:
        self._fast_model = model
        self._soothe_config = soothe_config

        if model:
            logger.debug("[IntakePass1] Initialized")
        else:
            logger.warning("[IntakePass1] No model provided, classifier disabled")

    async def classify(
        self,
        query: str,
        *,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> IntakePass1LLMResult:
        """Classify query as social or task.

        No retry on failure — fail-safe to task (is_task=True) so Pass 2 runs.

        Args:
            query: User input text.
            observability_metadata: Optional metadata for observability.
            goal_trace: Optional Langfuse trace context.

        Returns:
            IntakePass1LLMResult with is_task, confidence, social_response, reasoning.
        """
        if not self._fast_model:
            return self._fallback(query)

        try:
            result = await self._classify_llm(
                query,
                observability_metadata=observability_metadata,
                goal_trace=goal_trace,
            )
            logger.debug(
                "Pass1 classified: is_task=%s confidence=%s",
                result.is_task,
                result.confidence,
            )
            return result
        except Exception as exc:
            logger.warning(
                "Pass1 classification failed, fail-safe to task: %s",
                type(exc).__name__,
            )
            logger.debug("Pass1 error: %s", exc, exc_info=True)
            return self._fallback(query, error_context=exc)

    async def _classify_llm(
        self,
        query: str,
        *,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> IntakePass1LLMResult:
        """Single LLM call for Pass 1 classification."""
        messages = [
            SystemMessage(content=INTAKE_PASS1_SYSTEM_PROMPT),
            HumanMessage(content=f"{query}\n\n{INTAKE_PASS1_HUMAN_TASK}"),
        ]

        config = self._build_invoke_config(
            "classify_pass1",
            "intake.pass1",
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
        )

        schema = IntakePass1LLMResult.model_json_schema()

        async def _invoke() -> dict[str, Any]:
            return await invoke_structured_chat(
                self._fast_model,
                messages,
                json_schema=schema,
                schema_name="IntakePass1LLMResult",
                strict=True,
                config=config,
            )

        result_dict = await await_with_llm_call_policy(
            _invoke,
            config=llm_rate_limit_config_from(self._soothe_config),
        )

        if result_dict is None:
            raise ValueError("LLM returned None - structured output parsing failed")

        # Validate is_task is boolean
        if result_dict.get("is_task") not in (True, False):
            raise ValueError(f"Invalid is_task from LLM: {result_dict.get('is_task')!r}")

        # Validate confidence
        if result_dict.get("confidence") not in (
            IntakePass1Confidence.HIGH,
            IntakePass1Confidence.MEDIUM,
            IntakePass1Confidence.LOW,
        ):
            result_dict["confidence"] = IntakePass1Confidence.MEDIUM

        # Ensure social_response when is_task=False
        if (
            not result_dict.get("is_task")
            and not (result_dict.get("social_response") or "").strip()
        ):
            result_dict["social_response"] = "Hello! How can I help you today?"

        return IntakePass1LLMResult(**result_dict)

    def _fallback(
        self,
        query: str,
        *,
        error_context: Exception | None = None,
    ) -> IntakePass1LLMResult:
        """Fail-safe: treat as task so Pass 2 runs."""
        reason = type(error_context).__name__ if error_context else "no_model"
        logger.debug("Pass1 fallback to task (%s)", reason)
        return IntakePass1LLMResult(
            is_task=True,
            confidence=IntakePass1Confidence.LOW,
            social_response=None,
            reasoning=f"Fail-safe: {reason}",
        )

    def _build_invoke_config(
        self,
        purpose: str,
        component: str,
        *,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> dict[str, Any]:
        """Build RunnableConfig with Langfuse tracing."""
        from soothe.middleware._utils import create_llm_call_metadata

        if goal_trace is not None:
            return goal_trace.intake_invoke_config(
                purpose=purpose,
                component=f"classifier.{component}",
                phase="intake_pass1",
                extra_metadata=observability_metadata,
            )

        if self._soothe_config is not None:
            from soothe.utils.observability.langfuse import SootheLangfuse

            trace_name = (self._soothe_config.observability.langfuse.trace_name or "").strip()
            return SootheLangfuse(self._soothe_config).traced_llm(
                purpose=purpose,
                component=f"classifier.{component}",
                phase="intake_pass1",
                run_name=f"intake_pass1:{trace_name or 'query'}",
                extra_metadata=observability_metadata,
            )

        metadata = create_llm_call_metadata(
            purpose=purpose,
            component=f"classifier.{component}",
            phase="intake_pass1",
        )
        if observability_metadata:
            metadata.update(observability_metadata)
        return {"metadata": metadata}


__all__ = ["IntakePass1Classifier"]
