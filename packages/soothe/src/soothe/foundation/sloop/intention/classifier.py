"""Intent classifier implementation (RFC-225, RFC-630).

4-class LLM intake classification (``quiz`` | ``trivial`` | ``simple`` |
``complex``) via ``classify_intake``, driving ``route_by_intent`` branch
routing. Loop continuation is derived structurally inside ``StrangeLoop``
from the loaded checkpoint and is not a classifier concern.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage

from soothe.utils.llm.invoke_policy import (
    await_with_llm_call_policy,
    llm_rate_limit_config_from,
)
from soothe.utils.llm.structured import invoke_structured_chat

from .models import (
    IntakeClassificationLLMResult,
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
)
from .prompts import (
    INTAKE_CLASSIFICATION_PROMPT,
    INTAKE_CLASSIFICATION_RETRY_PROMPT,
)
from .quiz_messages import build_quiz_system_message

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class IntentClassifier:
    """LLM-driven intent classification (RFC-225, RFC-630).

    - 4-class intake label via a single structured LLM call.
    - No structural / continuation logic — that is owned by ``StrangeLoop``.
    - Robust fallback to ``complex`` on failure (fail-safe: full pipeline runs).

    Args:
        model: Fast LLM for classification (e.g., gpt-4o-mini).
        assistant_name: Name used in quiz fallback replies.
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

        if model:
            logger.info("[IntentClassifier] Initialized with structured output model")
        else:
            logger.warning("[IntentClassifier] No model provided, classification disabled")

    # -- Public API --------------------------------------------------------

    async def classify_intake(
        self,
        query: str,
        *,
        observability_metadata: dict[str, str] | None = None,
    ) -> IntentClassification:
        """Classify the query into a 4-class intake label (RFC-630).

        One structured LLM call with retry; fallback to ``complex`` so the full
        pipeline runs (fail-safe, RFC-630 §9.3).

        Args:
            query: User input text.
            observability_metadata: Optional metadata for observability.

        Returns:
            IntentClassification with ``intake_label`` ∈
            {``quiz``, ``trivial``, ``simple``, ``complex``} and ``intent_type``
            derived from it (``quiz`` → ``quiz``, else ``agentic``).
        """
        if not self._fast_model:
            return self._fallback(query)

        result: IntentClassification | None = None
        last_error: Exception | None = None

        for retry_mode in (False, True):
            try:
                result = await self._classify_intake_llm(
                    query,
                    retry_mode=retry_mode,
                    observability_metadata=observability_metadata,
                )
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Intake classification failed (%s), retrying...",
                    "retry" if retry_mode else "primary",
                )
                logger.debug("Intake classification error: %s", exc, exc_info=True)

        if result is None:
            logger.warning(
                "Intake classification failed after retry, using fallback (error: %s)",
                type(last_error).__name__ if last_error else "unknown",
            )
            return self._fallback(query, error_context=last_error)

        result = self._patch_missing_fields(result, query)

        logger.debug(
            "Intake classified: intake_label=%s complexity=%s",
            result.intake_label,
            result.task_complexity,
        )

        return result

    # -- Internal LLM calls ------------------------------------------------

    async def _classify_intake_llm(
        self,
        query: str,
        *,
        retry_mode: bool = False,
        observability_metadata: dict[str, str] | None = None,
    ) -> IntentClassification:
        """4-class intake LLM call with structured output (RFC-630).

        Uses `invoke_structured_chat` for thinking-model compatibility.
        Models in thinking mode reject `tool_choice=required`, so we use the
        structured_invoke fallback chain: function_calling → json_schema → json_mode.
        The LLM picks one of ``quiz``/``trivial``/``simple``/``complex``; the
        result is mapped onto ``intent_type`` so the quiz fast-path and event
        emission keep working.
        """
        current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        prompt_template = (
            INTAKE_CLASSIFICATION_RETRY_PROMPT if retry_mode else INTAKE_CLASSIFICATION_PROMPT
        )
        prompt = prompt_template.format(
            query=query,
            current_time=current_time,
            assistant_name=self._assistant_name,
        )

        config = self._build_invoke_config(
            "classify_intake",
            "intake.primary",
            observability_metadata=observability_metadata,
        )

        messages = [
            SystemMessage(content=build_quiz_system_message(self._assistant_name)),
            HumanMessage(content=prompt),
        ]

        schema = IntakeClassificationLLMResult.model_json_schema()
        try:

            async def _invoke() -> dict[str, Any]:
                return await invoke_structured_chat(
                    self._fast_model,
                    messages,
                    json_schema=schema,
                    schema_name="IntakeClassificationLLMResult",
                    strict=True,
                    config=config,
                )

            result_dict = await await_with_llm_call_policy(
                _invoke,
                config=llm_rate_limit_config_from(self._soothe_config),
            )
        except Exception:
            logger.exception("LLM intake classification call failed")
            raise

        if result_dict is None:
            raise ValueError("LLM returned None - structured output parsing failed")

        if result_dict.get("intake_label") not in (
            IntakeLabel.QUIZ,
            IntakeLabel.TRIVIAL,
            IntakeLabel.SIMPLE,
            IntakeLabel.COMPLEX,
        ):
            raise ValueError(f"Invalid intake_label from LLM: {result_dict.get('intake_label')!r}")

        llm_result = IntakeClassificationLLMResult(**result_dict)
        return llm_result.to_intent_classification()

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _build_quiz_intent() -> IntentClassification:
        """Build a quiz IntentClassification (fast-path hint bypass)."""
        return IntentClassification(
            intent_type="quiz",
            intake_label=IntakeLabel.QUIZ,
            reasoning=None,
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response=None,
        )

    def _fallback(
        self,
        query: str,
        *,
        error_context: Exception | None = None,
    ) -> IntentClassification:
        """Safe fallback to ``complex`` (RFC-630 §9.3): run the full pipeline."""
        reason = type(error_context).__name__ if error_context else "classification_disabled"
        logger.debug("Intake fallback to complex (%s)", reason)
        return IntentClassification(
            intent_type="agentic",
            intake_label=IntakeLabel.COMPLEX,
            reasoning="Let me run the full agent loop to work through this goal.",
            goal_description=query,
            task_complexity=TaskComplexity.COMPLEX,
            quiz_response=None,
        )

    def _patch_missing_fields(
        self,
        intent: IntentClassification,
        query: str,
    ) -> IntentClassification:
        """Patch missing goal_description and reasoning on agentic results (IG-518)."""
        if intent.intent_type == "agentic":
            if not intent.goal_description:
                intent.goal_description = query
                logger.debug("Patched missing goal_description")
            if not intent.reasoning:
                intent.reasoning = "I'll use tools to work through this goal."
                logger.debug("Patched missing reasoning")
        return intent

    def _build_invoke_config(
        self,
        purpose: str,
        component: str,
        *,
        observability_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build RunnableConfig with Langfuse tracing and call metadata."""
        try:
            from soothe.utils.observability.langfuse import build_traced_config

            return build_traced_config(
                self._soothe_config,
                purpose=purpose,
                component=f"classifier.{component}",
                phase="pre-stream",
                run_name="soothe:intent-classify",
                extra_metadata=observability_metadata,
                independent_trace=True,  # Ensure standalone root trace, not nested under strange-loop-graph
            )
        except Exception:
            from soothe.middleware._utils import create_llm_call_metadata

            metadata = create_llm_call_metadata(
                purpose=purpose,
                component=f"classifier.{component}",
                phase="pre-stream",
            )
            if observability_metadata:
                metadata.update(observability_metadata)
            return {"metadata": metadata}
