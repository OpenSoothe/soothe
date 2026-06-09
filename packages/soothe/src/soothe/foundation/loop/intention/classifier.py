"""Intent classifier implementation (RFC-225).

Two-value LLM classification (``quiz`` vs. ``agentic``). Loop continuation
is derived structurally inside ``AgentLoop`` from the loaded checkpoint
and is not a classifier concern.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage

from soothe.foundation.core.quiz_messages import build_quiz_system_message
from soothe.utils.llm.structured_invoke import invoke_structured_chat

from .models import (
    IntentClassification,
    IntentClassificationLLMResult,
    IntentHint,
    TaskComplexity,
)
from .prompts import (
    INTENT_CLASSIFICATION_PROMPT,
    INTENT_CLASSIFICATION_RETRY_PROMPT,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class IntentClassifier:
    """LLM-driven intent classification (RFC-225).

    - Quiz vs. agentic decision via a single structured LLM call.
    - No structural / continuation logic — that is owned by ``AgentLoop``.
    - Robust fallbacks to safe defaults on failure.

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

    async def classify_intent(
        self,
        query: str,
        *,
        observability_metadata: dict[str, str] | None = None,
        intent_hint: IntentHint | None = None,
    ) -> IntentClassification:
        """Classify the query as quiz or agentic.

        - ``intent_hint=quiz`` short-circuits to a quiz classification.
        - Long/complex queries (heuristic) skip the LLM and resolve as agentic.
        - Otherwise: one structured LLM call with retry; fallback to agentic.

        Args:
            query: User input text.
            observability_metadata: Optional metadata for observability.
            intent_hint: Optional bypass hint (``quiz`` only).

        Returns:
            IntentClassification with ``intent_type`` ∈ {``quiz``, ``agentic``}.
        """
        if intent_hint == IntentHint.QUIZ:
            logger.info("Intent hint bypass: quiz")
            return self._build_quiz_intent()

        if self._is_likely_agentic(query):
            logger.info("Heuristic bypass: query too long/complex for quiz, classifying as agentic")
            return self._build_agentic_intent(query)

        if not self._fast_model:
            return self._fallback_intent(query)

        result: IntentClassification | None = None
        last_error: Exception | None = None

        for retry_mode in (False, True):
            try:
                result = await self._classify_intent_llm(
                    query,
                    retry_mode=retry_mode,
                    observability_metadata=observability_metadata,
                )
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Intent classification failed (%s), retrying...",
                    "retry" if retry_mode else "primary",
                )
                logger.debug("Intent classification error: %s", exc, exc_info=True)

        if result is None:
            logger.warning(
                "Intent classification failed after retry, using fallback (error: %s)",
                type(last_error).__name__ if last_error else "unknown",
            )
            return self._fallback_intent(query, error_context=last_error)

        result = self._patch_missing_fields(result, query)

        logger.debug(
            "Intent classified: intent_type=%s complexity=%s",
            result.intent_type,
            result.task_complexity,
        )

        return result

    # -- Internal LLM calls ------------------------------------------------

    async def _classify_intent_llm(
        self,
        query: str,
        *,
        retry_mode: bool = False,
        observability_metadata: dict[str, str] | None = None,
    ) -> IntentClassification:
        """LLM quiz detection with structured output.

        Uses `invoke_structured_chat` for thinking-model compatibility.
        Models in thinking mode reject `tool_choice=required`, so we use the
        structured_invoke fallback chain: function_calling → json_schema → json_mode.
        """
        current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        prompt_template = (
            INTENT_CLASSIFICATION_RETRY_PROMPT if retry_mode else INTENT_CLASSIFICATION_PROMPT
        )
        prompt = prompt_template.format(
            query=query,
            current_time=current_time,
            assistant_name=self._assistant_name,
        )

        config = self._build_invoke_config(
            "classify_intent",
            "intent.primary",
            observability_metadata=observability_metadata,
        )

        messages = [
            SystemMessage(content=build_quiz_system_message(self._assistant_name)),
            HumanMessage(content=prompt),
        ]

        # Use invoke_structured_chat for thinking-model fallback support
        schema = IntentClassificationLLMResult.model_json_schema()
        try:
            result_dict = await invoke_structured_chat(
                self._fast_model,
                messages,
                json_schema=schema,
                schema_name="IntentClassificationLLMResult",
                strict=True,
                config=config,
            )
        except Exception:
            logger.exception("LLM intent classification call failed")
            raise

        if result_dict is None:
            raise ValueError("LLM returned None - structured output parsing failed")

        if result_dict.get("intent_type") not in ("agentic", "quiz"):
            raise ValueError(f"Invalid intent_type from LLM: {result_dict.get('intent_type')!r}")

        llm_result = IntentClassificationLLMResult(**result_dict)
        return llm_result.to_intent_classification()

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _build_quiz_intent() -> IntentClassification:
        """Build a quiz IntentClassification (fast-path hint bypass)."""
        return IntentClassification(
            intent_type="quiz",
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response=None,
        )

    @staticmethod
    def _build_agentic_intent(query: str) -> IntentClassification:
        """Build an agentic IntentClassification with medium complexity."""
        return IntentClassification(
            intent_type="agentic",
            goal_description=query,
            task_complexity=TaskComplexity.MEDIUM,
            quiz_response=None,
        )

    def _fallback_intent(
        self,
        query: str,
        *,
        error_context: Exception | None = None,
    ) -> IntentClassification:
        """Safe fallback to agentic when classification is unavailable or fails."""
        reason = type(error_context).__name__ if error_context else "classification_disabled"
        logger.debug("Intent fallback to agentic (%s)", reason)
        return self._build_agentic_intent(query)

    def _patch_missing_fields(
        self,
        intent: IntentClassification,
        query: str,
    ) -> IntentClassification:
        """Patch missing goal_description on agentic results."""
        if intent.intent_type == "agentic" and not intent.goal_description:
            intent.goal_description = query
            logger.debug("Patched missing goal_description")
        return intent

    # -- Heuristic classification -------------------------------------------

    @staticmethod
    def _is_likely_agentic(query: str) -> bool:
        """Heuristic: queries with >80 chars, >15 words, or >2 lines are agentic."""
        if len(query) > 80:
            return True
        if len(query.split()) > 15:
            return True
        if query.count("\n") >= 2:
            return True
        return False

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
                independent_trace=True,  # Ensure standalone root trace, not nested under agent-loop-graph
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
