"""Intent classifier implementation (IG-226, IG-250).

Quiz-only classification: LLM detects quiz vs agentic.
continue_thread vs new_goal is resolved structurally by the runner.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

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
    """LLM-driven intent classification system (IG-226).

    Pure LLM-driven classification with conversation context:
    - Intent classification (quiz/continue_thread/new_goal)
    - Routing classification (task complexity for execution path selection)
    - No keyword heuristics or language detection shortcuts

    Single structured LLM call (~2-4s latency) with:
    - Conversation context (last 8 messages)
    - Active goal context for thread continuation
    - Thread ID awareness
    - Robust fallbacks to safe defaults

    Args:
        model: Fast LLM for classification (e.g., gpt-4o-mini).
        assistant_name: Name used in quiz fallback replies.
    """

    def __init__(
        self,
        model: BaseChatModel | None,
        assistant_name: str = "Soothe",
        soothe_config: SootheConfig | None = None,
    ) -> None:
        """Initialize intent classifier.

        Args:
            model: Fast LLM for classification.
            assistant_name: Name used in responses.
            soothe_config: Soothe config for Langfuse tracing (optional).
        """
        self._fast_model = model
        self._assistant_name = assistant_name
        self._soothe_config = soothe_config

        # Pre-create structured output model for performance
        if model:
            self._intent_model = self._create_structured_model(model, IntentClassificationLLMResult)

            logger.info("[IntentClassifier] Initialized with structured output model")
        else:
            self._intent_model = None
            logger.warning("[IntentClassifier] No model provided, classification disabled")

    # -- Public API --------------------------------------------------------

    async def classify_intent(
        self,
        query: str,
        *,
        continue_thread: bool = False,
        observability_metadata: dict[str, str] | None = None,
        intent_hint: IntentHint | None = None,
    ) -> IntentClassification:
        """Quiz-only intent classification with structural continue/new_goal resolution.

        The LLM decides quiz vs agentic. The ``continue_thread`` parameter
        (set by the runner based on loop state) resolves agentic into
        continue_thread or new_goal.

        When ``intent_hint`` is ``quiz``, bypasses LLM classification entirely
        and returns a pre-built classification.

        Heuristic shortcut: queries longer than 80 chars, 15+ words, or 2+ lines
        are classified as agentic directly without an LLM call.

        Args:
            query: User input text.
            continue_thread: Whether this is a same-loop continuation (structural rule).
            observability_metadata: Optional metadata for observability.
            intent_hint: Suggested intent to bypass LLM classification (``quiz`` only).

        Returns:
            IntentClassification with intent type and routing attributes.
        """
        # Fast-path bypass when hint provided for quiz
        if intent_hint == IntentHint.QUIZ:
            logger.info(
                "Intent hint bypass: using suggested intent_type=%s",
                intent_hint.value,
            )
            return self._build_intent_from_hint(query, intent_hint, continue_thread=continue_thread)

        # Heuristic: long/complex queries are always agentic
        if self._is_likely_agentic(query):
            logger.info("Heuristic bypass: query too long/complex for quiz, classifying as agentic")
            return self._build_heuristic_agentic(query, continue_thread=continue_thread)

        # Fallback when classifier disabled
        if not self._fast_model or not self._intent_model:
            return self._fallback_intent(query, continue_thread=continue_thread)

        # Attempt classification with retry
        result: IntentClassification | None = None
        last_error: Exception | None = None

        for retry_mode in (False, True):
            try:
                result = await self._classify_intent_llm(
                    query,
                    retry_mode=retry_mode,
                    continue_thread=continue_thread,
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

        # Fallback on persistent failure
        if result is None:
            logger.warning(
                "Intent classification failed after retry, using fallback (error: %s)",
                type(last_error).__name__ if last_error else "unknown",
            )
            return self._fallback_intent(
                query, continue_thread=continue_thread, error_context=last_error
            )

        # Post-process: patch missing fields
        result = self._patch_missing_fields(result, query)

        logger.debug(
            "Intent classified: intent_type=%s reuse_goal=%s complexity=%s",
            result.intent_type,
            result.reuse_current_goal,
            result.task_complexity,
        )

        return result

    # -- Internal LLM calls ------------------------------------------------

    async def _classify_intent_llm(
        self,
        query: str,
        *,
        retry_mode: bool = False,
        continue_thread: bool = False,
        observability_metadata: dict[str, str] | None = None,
    ) -> IntentClassification:
        """LLM quiz detection with structured output."""
        current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        prompt_template = (
            INTENT_CLASSIFICATION_RETRY_PROMPT if retry_mode else INTENT_CLASSIFICATION_PROMPT
        )
        prompt = prompt_template.format(
            query=query,
            current_time=current_time,
        )

        # Build traced config with Langfuse callbacks + metadata
        config = self._build_invoke_config(
            "classify_intent",
            "intent.primary",
            observability_metadata=observability_metadata,
        )

        try:
            llm_result = await self._intent_model.ainvoke(prompt, config=config)
        except Exception:
            logger.exception("LLM intent classification call failed")
            raise

        # Validate result
        if llm_result is None:
            raise ValueError("LLM returned None - structured output parsing failed")

        if llm_result.intent_type not in ("agentic", "quiz"):
            raise ValueError(f"Invalid intent_type from LLM: {llm_result.intent_type!r}")

        return llm_result.to_intent_classification(continue_thread=continue_thread)

    # -- Model creation ----------------------------------------------------

    def _create_structured_model(
        self,
        base_model: BaseChatModel,
        schema: type[BaseModel],
    ) -> Any:
        """Create structured output model.

        Prefers function_calling over json_mode for better literal validation.

        Args:
            base_model: Base chat model.
            schema: Pydantic schema for structured output.

        Returns:
            Model with structured output support.
        """
        # Try function_calling first (best for literal validation)
        for method in ("function_calling", None, "json_mode"):
            try:
                if method is None:
                    return base_model.with_structured_output(schema)
                return base_model.with_structured_output(schema, method=method)
            except Exception:
                logger.debug("with_structured_output failed for method=%s", method, exc_info=True)

        # Final fallback
        return base_model.with_structured_output(schema, method="json_mode")

    # -- Helpers ------------------------------------------------------------

    def _build_intent_from_hint(
        self,
        query: str,
        hint: IntentHint,
        *,
        continue_thread: bool = False,
    ) -> IntentClassification:
        """Build intent classification from hint (bypasses LLM).

        Used when caller provides ``intent_hint=quiz`` to skip LLM classification.

        Args:
            query: Original user query.
            hint: Suggested intent type.
            continue_thread: Whether this is a same-loop continuation.

        Returns:
            IntentClassification with the hinted intent type.
        """
        if hint == IntentHint.QUIZ:
            return IntentClassification(
                intent_type="quiz",
                reuse_current_goal=False,
                goal_description=None,
                task_complexity=TaskComplexity.MINIMAL,
                quiz_response=None,  # Filled by _run_quiz if not piggybacked
            )
        elif hint == IntentHint.CONTINUE_THREAD:
            return IntentClassification(
                intent_type="continue_thread",
                reuse_current_goal=True,
                goal_description=query,
                task_complexity=TaskComplexity.MEDIUM,
            )
        elif hint == IntentHint.NEW_GOAL:
            return IntentClassification(
                intent_type="new_goal",
                reuse_current_goal=False,
                goal_description=query,
                task_complexity=TaskComplexity.MEDIUM,
            )
        else:
            # Fallback for unknown hint (should not happen with enum)
            return self._fallback_intent(query, continue_thread=continue_thread)

    def _fallback_intent(
        self,
        query: str,
        *,
        continue_thread: bool = False,
        error_context: Exception | None = None,
    ) -> IntentClassification:
        """Safe fallback intent when classification fails.

        Args:
            query: Original user query.
            continue_thread: Whether this is a same-loop continuation.
            error_context: Optional exception when falling back after classification failure.

        Returns:
            IntentClassification with safe defaults.
        """
        reason = type(error_context).__name__ if error_context else "classification_disabled"
        resolved_type = "continue_thread" if continue_thread else "new_goal"
        logger.debug("Intent fallback to %s (%s)", resolved_type, reason)
        return IntentClassification(
            intent_type=resolved_type,
            reuse_current_goal=continue_thread,
            goal_description=query,
            task_complexity=TaskComplexity.MEDIUM,
        )

    def _patch_missing_fields(
        self,
        intent: IntentClassification,
        query: str,
    ) -> IntentClassification:
        """Post-process intent to patch missing fields.

        Args:
            intent: Original intent classification.
            query: Original user query.

        Returns:
            IntentClassification with patched fields.
        """
        # Patch missing goal_description
        if intent.intent_type == "new_goal" and not intent.goal_description:
            intent.goal_description = query
            logger.debug("Patched missing goal_description")

        return intent

    # -- Heuristic classification -------------------------------------------

    @staticmethod
    def _is_likely_agentic(query: str) -> bool:
        """Check if query is too long/complex to be a simple quiz.

        Heuristic: queries with >80 chars, >15 words, or >2 lines are
        almost always agentic (not greetings/thanks/trivia).

        Args:
            query: User input text.

        Returns:
            True if query should be classified as agentic without LLM call.
        """
        if len(query) > 80:
            return True
        if len(query.split()) > 15:
            return True
        if query.count("\n") >= 2:
            return True
        return False

    def _build_heuristic_agentic(
        self,
        query: str,
        *,
        continue_thread: bool = False,
    ) -> IntentClassification:
        """Build agentic intent from heuristic (bypasses LLM).

        Args:
            query: Original user query.
            continue_thread: Whether this is a same-loop continuation.

        Returns:
            IntentClassification with agentic type and medium complexity.
        """
        resolved_type = "continue_thread" if continue_thread else "new_goal"
        return IntentClassification(
            intent_type=resolved_type,
            reuse_current_goal=continue_thread,
            goal_description=query,
            task_complexity=TaskComplexity.MEDIUM,
        )

    def _build_invoke_config(
        self,
        purpose: str,
        component: str,
        *,
        observability_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build RunnableConfig with Langfuse tracing and call metadata.

        Args:
            purpose: Classification purpose (classify_intent).
            component: Component identifier.
            observability_metadata: Extra metadata from caller.

        Returns:
            RunnableConfig dict for ``model.ainvoke(..., config=)``.
        """
        try:
            from soothe.utils.observability.langfuse import build_traced_config

            return build_traced_config(
                self._soothe_config,
                purpose=purpose,
                component=f"classifier.{component}",
                phase="pre-stream",
                run_name="soothe:intent-classify",
                extra_metadata=observability_metadata,
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
