"""Intent classifier implementation (IG-226, IG-250).

LLM-driven query intent classifier with conversation context awareness.
Pure LLM-driven classification - no keyword heuristics.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from soothe.utils.text_preview import preview_first

from .models import IntentClassification, RoutingClassification
from .prompts import (
    INTENT_CLASSIFICATION_PROMPT,
    INTENT_CLASSIFICATION_RETRY_PROMPT,
    ROUTING_PROMPT,
    ROUTING_RETRY_PROMPT,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


class IntentClassifier:
    """LLM-driven intent classification system (IG-226).

    Pure LLM-driven classification with conversation context:
    - Intent classification (chitchat/thread_continuation/new_goal)
    - Routing classification (task complexity for execution path selection)
    - No keyword heuristics or language detection shortcuts

    Single structured LLM call (~2-4s latency) with:
    - Conversation context (last 8 messages)
    - Active goal context for thread continuation
    - Thread ID awareness
    - Robust fallbacks to safe defaults

    Args:
        model: Fast LLM for classification (e.g., gpt-4o-mini).
        assistant_name: Name used in chitchat responses.
        config: Optional SootheConfig for tracing and provider capabilities.
    """

    def __init__(
        self,
        model: BaseChatModel | None,
        assistant_name: str = "Soothe",
        config: Any | None = None,
    ) -> None:
        """Initialize intent classifier.

        Args:
            model: Fast LLM for classification.
            assistant_name: Name used in responses.
            config: Optional SootheConfig for tracing.
        """
        self._fast_model = model
        self._assistant_name = assistant_name
        self._config = config

        # Pre-create structured output models for performance
        if model:
            # Apply LLM tracing wrapper to base model BEFORE structured output conversion
            # This allows tracing the actual AIMessage response, not the Pydantic result
            traced_model = model
            if config and hasattr(config, "llm_tracing") and config.llm_tracing.enabled:
                from soothe.utils.llm import LLMTracingWrapper

                traced_model = LLMTracingWrapper(model)
                logger.debug("[IntentClassifier] LLM tracing enabled for base model")

            self._intent_model = self._create_structured_model(traced_model, IntentClassification)
            self._routing_model = self._create_structured_model(traced_model, RoutingClassification)

            logger.info("[IntentClassifier] Initialized with structured output models")
        else:
            self._intent_model = None
            self._routing_model = None
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
    ) -> IntentClassification:
        """Unified intent classification with goal awareness.

        Single LLM call determines intent, goal handling, and routing complexity.
        Uses conversation context to detect thread continuation queries.

        Args:
            query: User input text.
            recent_messages: Conversation context for intent detection.
            active_goal_id: Current active goal ID in thread (if any).
            active_goal_description: Description of active goal.
            thread_id: Thread context for state awareness.

        Returns:
            IntentClassification with intent type and routing attributes.
        """
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

    async def classify_routing(
        self,
        query: str,
        *,
        recent_messages: list[Any] | None = None,
    ) -> RoutingClassification:
        """Routing classification for execution path selection.

        Args:
            query: User input text.
            recent_messages: Conversation context.

        Returns:
            RoutingClassification with routing complexity.
        """
        if not self._fast_model or not self._routing_model:
            return RoutingClassification(task_complexity="medium")

        conversation_context = self._format_conversation_context(recent_messages)

        result: RoutingClassification | None = None

        for retry_mode in (False, True):
            try:
                result = await self._classify_routing_llm(
                    query,
                    conversation_context=conversation_context,
                    retry_mode=retry_mode,
                )
                break
            except Exception:
                logger.warning("Routing classification failed, retrying...")

        if result is None:
            logger.warning("Routing classification failed, using default 'medium'")
            return RoutingClassification(task_complexity="medium")

        # Patch missing chitchat_response
        if result.task_complexity == "chitchat" and not result.chitchat_response:
            result.chitchat_response = self._generate_chitchat_response(query)

        logger.debug("Routing classified: task_complexity=%s", result.task_complexity)
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

        # Add tracing metadata
        metadata = self._create_llm_metadata("classify_intent", "intent.primary")

        try:
            result = await self._intent_model.ainvoke(prompt, config={"metadata": metadata})
        except Exception:
            logger.exception("LLM intent classification call failed")
            raise

        # Validate result
        if result is None:
            raise ValueError("LLM returned None - structured output parsing failed")

        if result.intent_type not in ("chitchat", "thread_continuation", "new_goal", "quiz"):
            raise ValueError(f"Invalid intent_type from LLM: {result.intent_type!r}")

        return result

    async def _classify_routing_llm(
        self,
        query: str,
        *,
        conversation_context: str,
        retry_mode: bool = False,
    ) -> RoutingClassification:
        """LLM routing classification with structured output."""
        current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        prompt_template = ROUTING_RETRY_PROMPT if retry_mode else ROUTING_PROMPT
        prompt = prompt_template.format(
            query=query,
            current_time=current_time,
            assistant_name=self._assistant_name,
            conversation_context=conversation_context if not retry_mode else "",
        )

        metadata = self._create_llm_metadata("classify_routing", "routing.primary")

        try:
            result = await self._routing_model.ainvoke(prompt, config={"metadata": metadata})
        except Exception:
            logger.exception("LLM routing classification call failed")
            raise

        if result is None:
            raise ValueError("LLM routing returned None")

        if result.task_complexity not in ("chitchat", "quiz", "medium", "complex"):
            raise ValueError(f"Invalid task_complexity: {result.task_complexity!r}")

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

        Args:
            messages: Recent conversation messages.
            max_messages: Maximum messages to include.
            preview_chars: Preview length per message.

        Returns:
            Formatted conversation context string.
        """
        if not messages:
            return ""

        lines = []
        from langchain_core.messages import HumanMessage

        for msg in messages[-max_messages:]:
            role = "User" if isinstance(msg, HumanMessage) else "Assistant"
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                content = str(content)

            preview = preview_first(content, preview_chars).strip()
            if preview:
                lines.append(f"{role}: {preview}")

        return "\n" + "\n".join(lines) if lines else ""

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

    def _fallback_intent(
        self,
        query: str,
        *,
        error_context: Exception | None = None,
    ) -> IntentClassification:
        """Safe fallback intent when classification fails.

        Args:
            query: Original user query.
            error_context: Optional exception for reasoning.

        Returns:
            IntentClassification with safe defaults (new_goal).
        """
        error_msg = type(error_context).__name__ if error_context else "classification disabled"
        return IntentClassification(
            intent_type="new_goal",
            reuse_current_goal=False,
            goal_description=query,
            task_complexity="medium",
            reasoning=f"Fallback: {error_msg}",
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
        # Patch missing chitchat_response
        if intent.intent_type == "chitchat" and not intent.chitchat_response:
            intent.chitchat_response = self._generate_chitchat_response(query)
            logger.debug("Patched missing chitchat_response")

        # Patch missing quiz_response
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

    def _generate_chitchat_response(self, query: str) -> str:
        """Generate chitchat response (pure LLM-driven, no language detection heuristics).

        Args:
            query: User query (LLM will detect language from context).

        Returns:
            Friendly greeting response.
        """
        # Pure fallback: simple template without language detection
        # LLM will have already detected language in the classification prompt
        return f"Hello! I'm {self._assistant_name}. How can I help you today?"

    def _generate_quiz_response(self, query: str) -> str:
        """Generate quiz response fallback (LLM knowledge query).

        Args:
            query: Quiz/trivia question.

        Returns:
            Factual answer placeholder (primary path uses piggybacked quiz_response).
        """
        # Fallback placeholder - primary path uses piggybacked quiz_response from classification
        # This is only used if LLM classification fails to provide quiz_response
        return f"I'll answer that question: {query}"

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

    def _create_llm_metadata(
        self,
        purpose: str,
        component: str,
    ) -> dict[str, str]:
        """Create metadata for LLM tracing.

        Args:
            purpose: Classification purpose (classify_intent/classify_routing).
            component: Component identifier.

        Returns:
            Metadata dict for LLM call config.
        """
        try:
            from soothe.middleware._utils import create_llm_call_metadata

            return create_llm_call_metadata(
                purpose=purpose,
                component=f"classifier.{component}",
                phase="pre-stream",
            )
        except Exception:
            # Fallback if middleware utils unavailable
            return {
                "purpose": purpose,
                "component": component,
                "phase": "pre-stream",
            }
