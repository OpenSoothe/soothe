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
from typing import TYPE_CHECKING, Literal

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
You are {assistant_name}, created by Dr. Xiaming Chen. Classify this request and respond with JSON only.
Current time: {current_time}

Request: {query}

{{"task_complexity":"chitchat"|"medium"|"complex","chitchat_response":"string or null"}}

chitchat=greetings/thanks/fillers needing no action.
medium=research/questions/tasks/debugging (DEFAULT when uncertain).
complex=architecture design/large migrations/major refactoring.
If chitchat, set chitchat_response to a warm reply in the user's language \
mentioning you're {assistant_name} and that you were created by Dr. Xiaming Chen. Otherwise null.\
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
            self._routing_model = fast_model.with_structured_output(RoutingResult, method="json_mode")
        else:
            self._routing_model = None

    # -- two-tier public API ------------------------------------------------

    async def classify_routing(self, query: str) -> RoutingResult:
        """Tier-1: fast routing classification (~2-4s).

        Returns task_complexity and, for chitchat, a piggybacked response.
        This is the minimum information needed to decide the execution path.

        Args:
            query: User input text.

        Returns:
            RoutingResult with task_complexity and optional chitchat_response.
        """
        if self._mode == "disabled" or not self._fast_model:
            return RoutingResult(task_complexity="medium")

        try:
            result = await self._llm_routing(query)
        except Exception:
            logger.exception("Tier-1 routing classification failed")
            return RoutingResult(task_complexity="medium")

        if result.task_complexity == "chitchat" and not result.chitchat_response:
            result.chitchat_response = self._fallback_chitchat_response(query)
            logger.debug("Patched missing chitchat_response for query: %s", query[:50])

        logger.debug("Tier-1 routing: task_complexity=%s", result.task_complexity)
        return result

    # -- internal LLM calls -------------------------------------------------

    async def _llm_routing(self, query: str) -> RoutingResult:
        """Tier-1 LLM call with compact routing prompt."""
        from datetime import UTC, datetime

        current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        prompt = _ROUTING_PROMPT.format(
            query=query,
            current_time=current_time,
            assistant_name=self._assistant_name,
        )
        return await self._routing_model.ainvoke(prompt)

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
            return f"你好! 我是 {name}, 由陈晓明博士创造。有什么可以帮你的吗?"
        return f"Hello! I'm {name}, created by Dr. Xiaming Chen. How can I help you today?"

    def _default_classification(self, reason: str = "Default") -> UnifiedClassification:
        """Safe default when everything fails."""
        return UnifiedClassification(
            task_complexity="medium",
            reasoning=reason,
        )
