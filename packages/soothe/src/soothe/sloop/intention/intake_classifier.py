"""Intake classifier: social vs task, with task complexity and short description."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from soothe_nano.llm.invoke_policy import (
    await_with_llm_call_policy,
    llm_rate_limit_config_from,
)
from soothe_nano.llm.structured import invoke_structured_chat

from .chitchat_fallbacks import pick_generic_chitchat_fallback
from .invoke_config import build_intake_invoke_config
from .models import (
    IntakeConfidence,
    IntakeLLMResult,
    ResponseLanguage,
    TaskComplexity,
)
from .prompts import (
    INTAKE_CLASSIFY_SYSTEM_PROMPT,
    INTAKE_SOCIAL_REPLY_HUMAN_TASK,
    INTAKE_SOCIAL_REPLY_PROMPT,
    build_intake_human_content,
    build_intake_system_prompt,
)
from .social_reply import (
    SocialReplyResult,
    coalesce_intake_dict,
    intake_json_schema,
)
from .structured_methods import INTAKE_JSON_FIRST_METHODS

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig
    from soothe.config.models import AssistantIdentity

logger = logging.getLogger(__name__)

# Shown on the TUI cognition card when intake classification fails, so it must
# read as plain friendly prose — never an exception name or other internal detail.
INTAKE_FALLBACK_REASONING = "I'll plan the next steps for this request."


def build_intake_task_fallback(
    *,
    response_language: ResponseLanguage | None = None,
) -> IntakeLLMResult:
    """Fail-safe intake verdict: treat the input as a task.

    `reasoning` is user-facing prose because it reaches the TUI cognition card.
    The underlying error stays in the logs.

    Args:
        response_language: Language carried over from the prior turn, when known.

    Returns:
        Low-confidence task result flagged as a fallback.
    """
    return IntakeLLMResult(
        is_task=True,
        confidence=IntakeConfidence.LOW,
        social_response=None,
        task_complexity=TaskComplexity.COMPLEX,
        task_short_description=None,
        response_language=response_language or ResponseLanguage.OTHER,
        reasoning=INTAKE_FALLBACK_REASONING,
        fallback=True,
    )


def _log_intake_result(result: IntakeLLMResult) -> None:
    """Log intake reasoning at info for log-file visibility."""
    reasoning = (result.reasoning or "").strip()
    if reasoning:
        logger.info(
            "Intake reasoning (is_task=%s confidence=%s): %s",
            result.is_task,
            result.confidence,
            reasoning,
        )
    logger.debug(
        "Intake classified: is_task=%s confidence=%s",
        result.is_task,
        result.confidence,
    )


class IntakeClassifier:
    """Intake classification: social vs task, plus task complexity and short description.

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
        assistant_identity: AssistantIdentity | None = None,
    ) -> None:
        self._fast_model = model
        self._soothe_config = soothe_config
        self._assistant_name = (assistant_name or "Soothe").strip() or "Soothe"
        self._assistant_identity = assistant_identity

        if model:
            logger.debug("[Intake] Initialized")
        else:
            logger.warning("[Intake] No model provided, classifier disabled")

    async def classify(
        self,
        query: str,
        *,
        prior_response_language: ResponseLanguage | None = None,
        ledger_messages: list[BaseMessage] | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
        parent_runnable_config: dict[str, Any] | None = None,
    ) -> IntakeLLMResult:
        """Classify query as social or task (with ledger context when provided).

        Social replies use a dedicated reply-only LLM call when the first
        structured call omits `social_response` before falling back to task routing.

        Args:
            query: User input text.
            ledger_messages: Optional projected historical goal user/ai message
                pairs (from the ledger) injected between the system prompt and
                the user message.
            observability_metadata: Optional metadata for observability.
            goal_trace: Optional Langfuse trace context.

        Returns:
            IntakeLLMResult with is_task, confidence, social_response, reasoning.
        """
        if not self._fast_model:
            fallback = self._fallback(query)
            _log_intake_result(fallback)
            return fallback

        try:
            result = await self._classify_llm(
                query,
                prior_response_language=prior_response_language,
                ledger_messages=ledger_messages,
                observability_metadata=observability_metadata,
                goal_trace=goal_trace,
                parent_runnable_config=parent_runnable_config,
            )
            if not result.is_task and not (result.social_response or "").strip():
                logger.warning(
                    "Intake social verdict still missing social_response; generating reply"
                )
                try:
                    reply = await self._generate_social_response(
                        query,
                        observability_metadata=observability_metadata,
                        goal_trace=goal_trace,
                        parent_runnable_config=parent_runnable_config,
                    )
                except Exception:
                    logger.warning(
                        "Intake dedicated social reply failed; using generic fallback",
                        exc_info=True,
                    )
                    reply = pick_generic_chitchat_fallback(result.response_language)
                result = result.model_copy(update={"social_response": reply})
            _log_intake_result(result)
            return result
        except Exception as exc:
            logger.warning(
                "Intake classification failed, fail-safe to task: %s",
                type(exc).__name__,
            )
            logger.debug("Intake error: %s", exc, exc_info=True)
            fallback = self._fallback(query, error_context=exc)
            _log_intake_result(fallback)
            return fallback

    async def _classify_llm(
        self,
        query: str,
        *,
        prior_response_language: ResponseLanguage | None = None,
        ledger_messages: list[BaseMessage] | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
        parent_runnable_config: dict[str, Any] | None = None,
    ) -> IntakeLLMResult:
        """Single LLM call for intake classification."""
        prior_wire = prior_response_language.value if prior_response_language else None
        messages: list[BaseMessage] = [
            SystemMessage(
                content=build_intake_system_prompt(
                    INTAKE_CLASSIFY_SYSTEM_PROMPT,
                    self._assistant_name,
                    identity=self._assistant_identity,
                )
            ),
            *(ledger_messages or []),
            HumanMessage(
                content=build_intake_human_content(
                    query,
                    prior_response_language=prior_wire,
                )
            ),
        ]

        config = build_intake_invoke_config(
            phase="intake_classify",
            purpose="classify_intake",
            component="intake.classify",
            soothe_config=self._soothe_config,
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
            inherit_callbacks_from=parent_runnable_config,
        )

        schema = intake_json_schema()

        async def _invoke() -> dict[str, Any]:
            return await invoke_structured_chat(
                self._fast_model,
                messages,
                json_schema=schema,
                schema_name="IntakeLLMResult",
                strict=True,
                config=config,
                methods=INTAKE_JSON_FIRST_METHODS,
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
            IntakeConfidence.HIGH,
            IntakeConfidence.LOW,
        ):
            result_dict["confidence"] = IntakeConfidence.HIGH

        result_dict = coalesce_intake_dict(result_dict)
        return IntakeLLMResult(**result_dict)

    async def _generate_social_response(
        self,
        query: str,
        *,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
        parent_runnable_config: dict[str, Any] | None = None,
    ) -> str:
        """Dedicated reply-only LLM call when classification omits social_response."""
        system_prompt = build_intake_system_prompt(
            INTAKE_SOCIAL_REPLY_PROMPT,
            self._assistant_name,
            identity=self._assistant_identity,
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"{query}\n\n{INTAKE_SOCIAL_REPLY_HUMAN_TASK}"),
        ]
        config = build_intake_invoke_config(
            phase="intake_classify",
            purpose="classify_intake_social_reply",
            component="intake.social_reply",
            soothe_config=self._soothe_config,
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
            inherit_callbacks_from=parent_runnable_config,
        )
        schema = SocialReplyResult.model_json_schema()
        schema["required"] = ["social_response"]

        async def _invoke() -> dict[str, Any]:
            return await invoke_structured_chat(
                self._fast_model,
                messages,
                json_schema=schema,
                schema_name="SocialReplyResult",
                strict=True,
                config=config,
                methods=INTAKE_JSON_FIRST_METHODS,
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
    ) -> IntakeLLMResult:
        """Fail-safe: treat as task."""
        reason = type(error_context).__name__ if error_context else "no_model"
        logger.debug("Intake fallback to task (%s)", reason)
        return build_intake_task_fallback()


__all__ = [
    "INTAKE_FALLBACK_REASONING",
    "IntakeClassifier",
    "build_intake_task_fallback",
]
