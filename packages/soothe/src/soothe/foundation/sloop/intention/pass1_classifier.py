"""Pass 1 classifier: social vs task (RFC-630 IG-554).

Binary decision with no prior context. Returns ``is_task`` boolean plus
``social_response`` for fast-path END when social.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage

from soothe.foundation.sloop.chitchat_fallbacks import pick_generic_chitchat_fallback
from soothe.utils.llm.invoke_policy import (
    await_with_llm_call_policy,
    llm_rate_limit_config_from,
)
from soothe.utils.llm.structured import StructuredOutputError, invoke_structured_chat

from .models import IntakePass1Confidence, IntakePass1LLMResult, IntakePass1SocialKind
from .pass1_social_response import (
    Pass1SocialReplyLLMResult,
    coalesce_pass1_dict,
    pass1_json_schema,
)
from .prompts import (
    INTAKE_PASS1_HUMAN_TASK,
    INTAKE_PASS1_SOCIAL_REPLY_HUMAN_TASK,
    INTAKE_PASS1_SOCIAL_REPLY_PROMPT,
    INTAKE_PASS1_SYSTEM_PROMPT,
    build_intake_pass1_system_prompt,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


def _log_pass1_result(result: IntakePass1LLMResult) -> None:
    """Log Pass 1 reasoning at info for log-file visibility (IG-554)."""
    reasoning = (result.reasoning or "").strip()
    if reasoning:
        logger.info(
            "Pass1 reasoning (is_task=%s confidence=%s): %s",
            result.is_task,
            result.confidence,
            reasoning,
        )
    logger.debug(
        "Pass1 classified: is_task=%s confidence=%s",
        result.is_task,
        result.confidence,
    )


class IntakePass1Classifier:
    """Pass 1: binary social vs task classification (RFC-630 IG-554).

    Clean decision boundary with no prior context projection. Returns ``is_task``
    boolean and ``social_response`` for fast-path END on social queries.

    Args:
        model: Fast LLM for classification.
        soothe_config: Optional config for rate limiting and tracing.
        assistant_name: Display name for dedicated social-reply fallback.
    """

    def __init__(
        self,
        model: BaseChatModel | None,
        soothe_config: SootheConfig | None = None,
        *,
        assistant_name: str = "Soothe",
    ) -> None:
        self._fast_model = model
        self._soothe_config = soothe_config
        self._assistant_name = (assistant_name or "Soothe").strip() or "Soothe"

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

        Social replies use a dedicated reply-only LLM call when the first
        structured call omits ``social_response`` before falling back to task routing.

        Args:
            query: User input text.
            observability_metadata: Optional metadata for observability.
            goal_trace: Optional Langfuse trace context.

        Returns:
            IntakePass1LLMResult with is_task, confidence, social_response, reasoning.
        """
        if not self._fast_model:
            fallback = self._fallback(query)
            _log_pass1_result(fallback)
            return fallback

        try:
            result = await self._classify_llm_with_output_retry(
                query,
                observability_metadata=observability_metadata,
                goal_trace=goal_trace,
            )
            if not result.is_task and not (result.social_response or "").strip():
                logger.warning(
                    "Pass1 social verdict still missing social_response; generating reply"
                )
                try:
                    reply = await self._generate_social_response(
                        query,
                        observability_metadata=observability_metadata,
                        goal_trace=goal_trace,
                    )
                except Exception:
                    logger.warning(
                        "Pass1 dedicated social reply failed; using generic fallback",
                        exc_info=True,
                    )
                    reply = pick_generic_chitchat_fallback(query)
                result = result.model_copy(update={"social_response": reply})
            _log_pass1_result(result)
            return result
        except Exception as exc:
            logger.warning(
                "Pass1 classification failed, fail-safe to task: %s",
                type(exc).__name__,
            )
            logger.debug("Pass1 error: %s", exc, exc_info=True)
            fallback = self._fallback(query, error_context=exc)
            _log_pass1_result(fallback)
            return fallback

    async def _classify_llm_with_output_retry(
        self,
        query: str,
        *,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> IntakePass1LLMResult:
        """Run Pass 1 LLM classification with one retry on structured-output failure."""
        try:
            return await self._classify_llm(
                query,
                observability_metadata=observability_metadata,
                goal_trace=goal_trace,
            )
        except StructuredOutputError:
            logger.warning("Pass1 structured output failed; retrying classification once")
            return await self._classify_llm(
                query,
                observability_metadata=observability_metadata,
                goal_trace=goal_trace,
            )

    async def _classify_llm(
        self,
        query: str,
        *,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> IntakePass1LLMResult:
        """Single LLM call for Pass 1 classification."""
        messages = [
            SystemMessage(
                content=build_intake_pass1_system_prompt(
                    INTAKE_PASS1_SYSTEM_PROMPT,
                    self._assistant_name,
                )
            ),
            HumanMessage(content=f"{query}\n\n{INTAKE_PASS1_HUMAN_TASK}"),
        ]

        config = self._build_invoke_config(
            "classify_pass1",
            "intake.pass1",
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
        )

        schema = pass1_json_schema(require_social_response=True)

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

        if result_dict.get("is_task") not in (True, False):
            raise ValueError(f"Invalid is_task from LLM: {result_dict.get('is_task')!r}")

        if result_dict.get("confidence") not in (
            IntakePass1Confidence.HIGH,
            IntakePass1Confidence.MEDIUM,
            IntakePass1Confidence.LOW,
        ):
            result_dict["confidence"] = IntakePass1Confidence.MEDIUM

        if result_dict.get("is_task") is True:
            result_dict.setdefault("social_kind", IntakePass1SocialKind.OTHER)

        result_dict = coalesce_pass1_dict(result_dict)
        return IntakePass1LLMResult(**result_dict)

    async def _generate_social_response(
        self,
        query: str,
        *,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> str:
        """Dedicated reply-only LLM call when classification omits social_response."""
        system_prompt = build_intake_pass1_system_prompt(
            INTAKE_PASS1_SOCIAL_REPLY_PROMPT,
            self._assistant_name,
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"{query}\n\n{INTAKE_PASS1_SOCIAL_REPLY_HUMAN_TASK}"),
        ]
        config = self._build_invoke_config(
            "classify_pass1_social_reply",
            "intake.pass1_social_reply",
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
        )
        schema = Pass1SocialReplyLLMResult.model_json_schema()
        schema["required"] = ["social_response"]

        async def _invoke() -> dict[str, Any]:
            return await invoke_structured_chat(
                self._fast_model,
                messages,
                json_schema=schema,
                schema_name="Pass1SocialReplyLLMResult",
                strict=True,
                config=config,
            )

        result_dict = await await_with_llm_call_policy(
            _invoke,
            config=llm_rate_limit_config_from(self._soothe_config),
        )
        if result_dict is None:
            raise ValueError("Social reply LLM returned None")
        reply = str(result_dict.get("social_response") or "").strip()
        if not reply:
            raise ValueError("Social reply LLM returned empty social_response")
        return reply

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
            social_kind=IntakePass1SocialKind.OTHER,
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
