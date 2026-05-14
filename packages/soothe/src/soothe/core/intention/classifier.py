"""Intent classifier implementation (IG-226, IG-250).

LLM-driven query intent classifier with conversation context awareness.
Pure LLM-driven classification - no keyword heuristics.
Supports intent_hint parameter to bypass LLM for known intent types.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from soothe.utils.text_preview import preview_first

from .models import IntentClassification, IntentHint, TaskComplexity
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
            self._intent_model = self._create_structured_model(model, IntentClassification)

            logger.info("[IntentClassifier] Initialized with structured output model")
        else:
            self._intent_model = None
            logger.warning("[IntentClassifier] No model provided, classification disabled")

    # -- Public API --------------------------------------------------------

    async def classify_intent(
        self,
        query: str,
        *,
        recent_messages: list[Any] | None = None,
        active_goal_id: str | None = None,
        active_goal_description: str | None = None,
        thread_id: str | None = None,
        observability_metadata: dict[str, str] | None = None,
        intent_hint: IntentHint | None = None,
    ) -> IntentClassification:
        """Unified intent classification with goal awareness.

        Single LLM call determines intent, goal handling, and routing complexity.
        Uses conversation context to detect thread continuation queries.

        When ``intent_hint`` is ``quiz``, bypasses LLM classification entirely
        and returns a pre-built classification.

        Args:
            query: User input text.
            recent_messages: Conversation context for intent detection.
            active_goal_id: Current active goal ID in thread (if any).
            active_goal_description: Description of active goal.
            thread_id: Thread context for state awareness.
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
            return self._build_intent_from_hint(query, intent_hint)

        # Fallback when classifier disabled
        if not self._fast_model or not self._intent_model:
            return self._fallback_intent(query)

        # Build conversation context
        conversation_context = self._format_conversation_context(recent_messages)

        # Build active goal context
        active_goal_context = self._format_active_goal_context(
            active_goal_id, active_goal_description
        )

        thread_id_display = thread_id or "new-thread"

        # Attempt classification with retry
        result: IntentClassification | None = None
        last_error: Exception | None = None

        for retry_mode in (False, True):
            try:
                result = await self._classify_intent_llm(
                    query,
                    conversation_context=conversation_context,
                    active_goal_context=active_goal_context,
                    thread_id=thread_id_display,
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

        # Fallback on persistent failure
        if result is None:
            logger.warning(
                "Intent classification failed after retry, using fallback (error: %s)",
                type(last_error).__name__ if last_error else "unknown",
            )
            return self._fallback_intent(query, error_context=last_error)

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
        conversation_context: str,
        active_goal_context: str,
        thread_id: str,
        retry_mode: bool = False,
        observability_metadata: dict[str, str] | None = None,
    ) -> IntentClassification:
        """LLM intent classification with structured output."""
        current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        prompt_template = (
            INTENT_CLASSIFICATION_RETRY_PROMPT if retry_mode else INTENT_CLASSIFICATION_PROMPT
        )
        prompt = prompt_template.format(
            query=query,
            current_time=current_time,
            assistant_name=self._assistant_name,
            conversation_context=conversation_context if not retry_mode else "",
            active_goal_context=active_goal_context,
            thread_id=thread_id,
        )

        # Build traced config with Langfuse callbacks + metadata
        config = self._build_invoke_config(
            "classify_intent",
            "intent.primary",
            observability_metadata=observability_metadata,
        )

        try:
            result = await self._intent_model.ainvoke(prompt, config=config)
        except Exception:
            logger.exception("LLM intent classification call failed")
            raise

        # Validate result
        if result is None:
            raise ValueError("LLM returned None - structured output parsing failed")

        if result.intent_type not in ("continue_thread", "new_goal", "quiz"):
            raise ValueError(f"Invalid intent_type from LLM: {result.intent_type!r}")

        return result

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

    def _format_conversation_context(
        self,
        messages: list[Any] | None,
        *,
        max_messages: int = 8,
        preview_chars: int = 200,
    ) -> str:
        """Format conversation messages for LLM prompt.

        Uses ``<user>`` / ``<assistant>`` XML blocks (IG-363), matching AgentLoop plan
        excerpt style; includes Human and AI turns only (skips tool/system messages).

        Args:
            messages: Recent conversation messages.
            max_messages: Maximum messages to include.
            preview_chars: Preview length per message.

        Returns:
            Formatted conversation context string.
        """
        if not messages:
            return ""

        from langchain_core.messages import AIMessage, HumanMessage

        lines: list[str] = []
        for msg in messages[-max_messages:]:
            if isinstance(msg, HumanMessage):
                tag = "user"
            elif isinstance(msg, AIMessage):
                tag = "assistant"
            else:
                continue
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                content = str(content)

            preview = preview_first(content, preview_chars).strip()
            if preview:
                lines.append(f"<{tag}>\n{preview}\n</{tag}>")

        return "\n\n".join(lines) if lines else ""

    def _format_active_goal_context(
        self,
        goal_id: str | None,
        goal_description: str | None,
    ) -> str:
        """Format active goal context for LLM prompt.

        Args:
            goal_id: Active goal ID.
            goal_description: Active goal description.

        Returns:
            Formatted active goal context string.
        """
        if goal_id and goal_description:
            preview = preview_first(goal_description, 80)
            return f"{goal_id}: {preview}"
        elif goal_id:
            return f"{goal_id} (active)"
        else:
            return "None (no active goal in thread)"

    def _build_intent_from_hint(
        self,
        query: str,
        hint: IntentHint,
    ) -> IntentClassification:
        """Build intent classification from hint (bypasses LLM).

        Used when caller provides ``intent_hint=quiz`` to skip LLM classification.

        Args:
            query: Original user query.
            hint: Suggested intent type.

        Returns:
            IntentClassification with the hinted intent type.
        """
        if hint == IntentHint.QUIZ:
            return IntentClassification(
                intent_type="quiz",
                reuse_current_goal=False,
                goal_description=None,
                task_complexity=TaskComplexity.MINIMAL,
                quiz_response=None,  # Filled by _run_quiz (default-role model)
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
            return self._fallback_intent(query)

    def _fallback_intent(
        self,
        query: str,
        *,
        error_context: Exception | None = None,
    ) -> IntentClassification:
        """Safe fallback intent when classification fails.

        Args:
            query: Original user query.
            error_context: Optional exception when falling back after classification failure.

        Returns:
            IntentClassification with safe defaults (new_goal).
        """
        reason = type(error_context).__name__ if error_context else "classification_disabled"
        logger.debug("Intent fallback to new_goal (%s)", reason)
        return IntentClassification(
            intent_type="new_goal",
            reuse_current_goal=False,
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
        # Patch missing quiz_response (greetings and factual piggyback)
        if intent.intent_type == "quiz" and not intent.quiz_response:
            intent.quiz_response = self._generate_quiz_response(query)
            logger.debug("Patched missing quiz_response")

        # Patch missing goal_description
        if intent.intent_type == "new_goal" and not intent.goal_description:
            intent.goal_description = query
            logger.debug("Patched missing goal_description")

        # Patch missing friendly_message (IG-287)
        if intent.intent_type == "new_goal" and not intent.friendly_message:
            intent.friendly_message = self._generate_friendly_message(query)
            logger.debug("Patched missing friendly_message")

        return intent

    def _generate_quiz_response(self, query: str) -> str:
        """Template fallback when classification omits ``quiz_response``."""
        return f"Hello! I'm {self._assistant_name}. How can I help you today?"

    def _generate_friendly_message(self, query: str) -> str:
        """Generate friendly message fallback (IG-287).

        Args:
            query: User query text.

        Returns:
            Friendly task reinterpretation placeholder.
        """
        # Fallback placeholder - primary path uses piggybacked friendly_message from classification
        # This is only used if LLM classification fails to provide friendly_message
        return f"I will work on: {query}"

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
