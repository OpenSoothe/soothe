"""Unified LLM-based routing classification system.

This module provides fast LLM-based routing classification:

- **Routing:** A fast LLM call (~2-4s) determines chitchat
  vs. non-chitchat. Chitchat queries are answered immediately.
  Non-chitchat queries proceed to planning.

Architecture Decision (RFC-0016):
- Routing is a tiny prompt (~100 input tokens, 4 output fields) for
  fast classification. Chitchat queries are answered immediately.
- Planning handles intent classification and plan generation in a single call.
- Returns safe default ("medium") if LLM fails or unavailable.

Classification Tiers:
- chitchat: Simple greetings and conversational fillers (skips planning/memory)
- medium: Questions requiring research/planning, multi-step tasks (default)
- complex: Architecture design, migrations, large refactoring
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def _looks_chinese(text: str) -> bool:
    """Return True if the text contains CJK Unified Ideographs."""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


CapabilityDomain = Literal["research", "workspace", "execute", "data", "browse", "reason", "compose"]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class RoutingResult(BaseModel):
    """Tier-1 fast routing result (2 fields only)."""

    task_complexity: Literal["chitchat", "medium", "complex"] = Field(description="chitchat | medium | complex")
    chitchat_response: str | None = Field(
        default=None,
        description="Friendly response when chitchat, null otherwise.",
    )
    preferred_subagent: str | None = Field(
        default=None,
        description="Preferred subagent name for direct routing (e.g., 'browser', 'claude').",
    )
    routing_hint: str | None = Field(
        default=None,
        description="Routing hint: 'subagent', 'tool', 'llm_only', etc.",
    )


class UnifiedClassification(BaseModel):
    """Routing classification result."""

    task_complexity: Literal["chitchat", "medium", "complex"] = Field(
        description="Query complexity for routing: chitchat (direct LLM), medium (subagent), complex (Claude)"
    )
    chitchat_response: str | None = Field(
        default=None,
        description="Direct response for chitchat queries. Only set when task_complexity is 'chitchat'.",
    )
    preferred_subagent: str | None = Field(
        default=None,
        description="Preferred subagent name for direct routing (e.g., 'browser', 'claude').",
    )
    routing_hint: str | None = Field(
        default=None,
        description="Routing hint: 'subagent', 'tool', 'llm_only', etc.",
    )
    reasoning: str | None = Field(default=None, description="Brief explanation of classification")

    @staticmethod
    def from_routing(routing: RoutingResult) -> UnifiedClassification:
        """Create UnifiedClassification from routing result.

        Args:
            routing: Routing result.

        Returns:
            UnifiedClassification instance.
        """
        return UnifiedClassification(
            task_complexity=routing.task_complexity,
            chitchat_response=routing.chitchat_response,
            preferred_subagent=routing.preferred_subagent,
            routing_hint=routing.routing_hint,
        )


# ---------------------------------------------------------------------------
# Prompts -- kept compact to minimise input/output tokens
# ---------------------------------------------------------------------------

_ROUTING_PROMPT = """\
You are {assistant_name}. Classify this request.
Current time: {current_time}
{conversation_context}
Request: {query}

CRITICAL OUTPUT RULES:
- Return ONLY valid JSON.
- "task_complexity" MUST be exactly one of: "chitchat", "medium", "complex".
- For "chitchat", provide a short friendly "chitchat_response" string.
- For "medium" or "complex", set "chitchat_response" to null.
- Do not output placeholders, punctuation, comments, markdown, or extra keys.

Required JSON shape:
{{"task_complexity": "chitchat"|"medium"|"complex", "chitchat_response": string|null}}

Classification rules:
- chitchat: Greetings, thanks, fillers needing no action. Set chitchat_response to a short,
  direct reply in the user's language.
- medium: Research, questions, tasks, debugging, follow-up actions. DEFAULT when uncertain.
  chitchat_response=null.
- complex: Architecture design, large migrations, major refactoring. chitchat_response=null.

IMPORTANT: If the request refers to prior context (e.g. "translate that", "summarize the above",
"explain more", "continue"), classify as "medium" NOT "chitchat".\
"""

_ROUTING_RETRY_PROMPT = """\
You are {assistant_name}. Re-classify this request.
Current time: {current_time}

Request: {query}

CRITICAL OUTPUT RULES:
- Return ONLY valid JSON.
- "task_complexity" MUST be exactly one of: "chitchat", "medium", "complex".
- For "chitchat", provide a short friendly "chitchat_response" string.
- For "medium" or "complex", set "chitchat_response" to null.
- Do not output placeholders, punctuation, comments, markdown, or extra keys.

Required JSON shape:
{{"task_complexity": "chitchat"|"medium"|"complex", "chitchat_response": string|null}}\
"""

# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


class UnifiedClassifier:
    """LLM-based routing classification system.

    Use ``classify_routing`` for fast routing classification.
    Planning handles intent classification and plan generation.

    Args:
        fast_model: Fast LLM for classification (e.g., gpt-4o-mini).
        classification_mode: "llm" or "disabled".
        assistant_name: Name used in chitchat responses.
    """

    def __init__(
        self,
        fast_model: BaseChatModel | None = None,
        classification_mode: Literal["llm", "disabled"] = "llm",
        assistant_name: str = "Soothe",
    ) -> None:
        """Initialize the unified classifier.

        Args:
            fast_model: Fast LLM for classification (e.g., gpt-4o-mini).
            classification_mode: "llm" or "disabled".
            assistant_name: Name used in chitchat responses.
        """
        self._fast_model = fast_model
        self._mode = classification_mode
        self._assistant_name = assistant_name

        if fast_model:
            self._routing_model = self._create_routing_model(fast_model)
        else:
            self._routing_model = None

    # -- two-tier public API ------------------------------------------------

    async def classify_routing(
        self,
        query: str,
        *,
        recent_messages: list[Any] | None = None,
    ) -> RoutingResult:
        """Tier-1: fast routing classification (~2-4s).

        Returns task_complexity and, for chitchat, a piggybacked response.
        This is the minimum information needed to decide the execution path.

        Args:
            query: User input text.
            recent_messages: Optional recent conversation messages to provide
                context for classification (helps distinguish follow-up actions
                like "translate that" from standalone chitchat).

        Returns:
            RoutingResult with task_complexity and optional chitchat_response.
        """
        if self._mode == "disabled" or not self._fast_model:
            return RoutingResult(task_complexity="medium")

        # Build conversation context for the prompt
        conversation_context = ""
        if recent_messages:
            lines = []
            for msg in recent_messages:
                from langchain_core.messages import HumanMessage

                role = "User" if isinstance(msg, HumanMessage) else "Assistant"
                content = getattr(msg, "content", "")
                if not isinstance(content, str):
                    content = str(content)
                preview = content[:200].strip()
                if preview:
                    lines.append(f"{role}: {preview}")
            if lines:
                conversation_context = "\n\nRecent conversation:\n" + "\n".join(lines[-8:])

        attempts: tuple[tuple[bool, str], ...] = (
            (False, "primary"),
            (True, "retry"),
        )
        result: RoutingResult | None = None
        last_error: Exception | None = None

        for retry_mode, label in attempts:
            try:
                result = await self._llm_routing(
                    query,
                    conversation_context=conversation_context,
                    retry_mode=retry_mode,
                )
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Tier-1 routing classification attempt failed (%s), retrying...",
                    label,
                )
                logger.debug("Routing failure details: %s", exc, exc_info=True)

        if result is None:
            logger.warning(
                "Tier-1 routing classification failed after retry, using default 'medium' (last error: %s)",
                type(last_error).__name__ if last_error else "unknown",
            )
            return RoutingResult(task_complexity="medium")

        if result.task_complexity == "chitchat" and not result.chitchat_response:
            result.chitchat_response = self._fallback_chitchat_response(query)
            logger.debug("Patched missing chitchat_response for query: %s", query[:50])

        logger.debug("Tier-1 routing: task_complexity=%s", result.task_complexity)
        return result

    # -- internal LLM calls -------------------------------------------------

    async def _llm_routing(
        self,
        query: str,
        *,
        conversation_context: str = "",
        retry_mode: bool = False,
    ) -> RoutingResult:
        """Tier-1 LLM call with compact routing prompt."""
        from datetime import UTC, datetime

        current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        prompt_template = _ROUTING_RETRY_PROMPT if retry_mode else _ROUTING_PROMPT
        prompt = prompt_template.format(
            query=query,
            current_time=current_time,
            assistant_name=self._assistant_name,
            conversation_context=conversation_context if not retry_mode else "",
        )

        try:
            result = await self._routing_model.ainvoke(prompt)
        except Exception:
            logger.exception("LLM routing call failed")
            raise

        # Ensure parsed output exists and obeys strict literal contract.
        if result is None:
            msg = "LLM returned None - structured output parsing failed"
            raise ValueError(msg)

        if not result.task_complexity or result.task_complexity not in ("chitchat", "medium", "complex"):
            msg = f"Invalid task_complexity from LLM: {result.task_complexity!r}"
            raise ValueError(msg)

        return result

    @staticmethod
    def _create_routing_model(fast_model: BaseChatModel) -> Any:
        """Create a robust structured-output model for routing classification.

        Prefers function-calling over json_mode because certain providers can
        emit malformed literal content under json_mode for strict enums.
        """
        methods = ("function_calling", None, "json_mode")
        for method in methods:
            try:
                if method is None:
                    return fast_model.with_structured_output(RoutingResult)
                return fast_model.with_structured_output(RoutingResult, method=method)
            except Exception:
                logger.debug("with_structured_output init failed for method=%s", method, exc_info=True)

        # Final fallback preserves legacy behavior if all attempts failed.
        return fast_model.with_structured_output(RoutingResult, method="json_mode")

    # -- helpers ------------------------------------------------------------

    def _fallback_chitchat_response(self, query: str) -> str:
        """Generate a default chitchat response when the LLM omits one.

        Args:
            query: Original user query (used for language detection heuristic).

        Returns:
            A friendly greeting string.
        """
        name = self._assistant_name
        if _looks_chinese(query):
            return f"你好! 我是 {name}。有什么可以帮你的吗?"
        return f"Hello! I'm {name}. How can I help you today?"

    def _default_classification(self, reason: str = "Default") -> UnifiedClassification:
        """Safe default when everything fails."""
        return UnifiedClassification(
            task_complexity="medium",
            reasoning=reason,
        )
