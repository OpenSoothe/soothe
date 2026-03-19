"""Unified LLM-based classification system.

This module provides a single classification system that uses fast LLM
for intelligent query analysis. It determines:

1. Task complexity (for routing and optimization)
2. Plan-only intent (for execution control)

Architecture Decision (RFC-0012):
- Single fast LLM call provides all classifications at once
- No keyword maintenance or token-count heuristics
- Handles multilingual and nuanced queries semantically
- Returns safe default ("medium") if LLM fails or unavailable

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


class UnifiedClassification(BaseModel):
    """Result of unified LLM classification."""

    task_complexity: Literal["chitchat", "medium", "complex"] = Field(
        description="Query complexity for routing: chitchat (direct LLM), medium (subagent), complex (Claude)"
    )
    is_plan_only: bool = Field(description="True if user only wants planning without execution")
    template_intent: Literal["question", "search", "analysis", "implementation"] | None = Field(
        default=None, description="Template intent for planning (question|search|analysis|implementation|null)"
    )
    reasoning: str | None = Field(default=None, description="Brief explanation of classification")


_UNIFIED_CLASSIFICATION_PROMPT = """\
Current time: {current_time}

Classify this user request for routing decisions.

User request: {query}

Response format (JSON only, no additional text):
{{
  "task_complexity": "chitchat" | "medium" | "complex",
  "is_plan_only": true | false,
  "template_intent": "question" | "search" | "analysis" | "implementation" | null,
  "reasoning": "brief explanation"
}}

Classification guide:
- chitchat: Simple greetings/fillers needing no action (hello, thanks, 你好)
- medium: Current events, research, debugging, planning, multi-step tasks (DEFAULT)
- complex: Architecture design, migrations, large refactoring

Template intent guide:
- question: User is asking a question (who/what/where/when/why/how)
- search: User wants to search/find information (search/find/look up)
- analysis: User wants analysis (analyze/review/examine/investigate)
- implementation: User wants to build/create something (implement/create/build/write)
- null: Chitchat queries or queries that don't fit other categories

Rules:
- Use semantic complexity, NOT query length
- Current events/research/debugging → medium (even if short)
- "plan only" → is_plan_only=true
- chitchat queries → template_intent=null
- When uncertain → medium complexity, appropriate template_intent or null
"""


class UnifiedClassifier:
    """Unified LLM-based classification system.

    Uses fast LLM for all classifications with no fallback to heuristics.
    Returns safe default if LLM unavailable.

    Args:
        fast_model: Fast LLM for classification (e.g., gpt-4o-mini).
        classification_mode: "llm" or "disabled".
    """

    def __init__(
        self,
        fast_model: BaseChatModel | None = None,
        classification_mode: Literal["llm", "disabled"] = "llm",
    ) -> None:
        """Initialize the unified classifier.

        Args:
            fast_model: Fast LLM for classification (e.g., gpt-4o-mini).
            classification_mode: "llm" or "disabled".
        """
        self._fast_model = fast_model
        self._mode = classification_mode

        # Use structured output if model available
        if fast_model:
            # Use json_mode for broader API compatibility (works with idealab, etc.)
            self._structured_model = fast_model.with_structured_output(UnifiedClassification, method="json_mode")
        else:
            self._structured_model = None

    async def classify(self, query: str) -> UnifiedClassification:
        """Classify query for routing decisions.

        Uses fast LLM for all classifications. No fallback to heuristics.

        Args:
            query: User input text.

        Returns:
            UnifiedClassification with routing decisions.
        """
        # Disabled mode (return safe default)
        if self._mode == "disabled":
            return self._default_classification("Classification disabled")

        # No fast model available (return safe default)
        if not self._fast_model:
            logger.warning("No fast model available for classification, using safe default")
            return self._default_classification("No fast model configured")

        # LLM classification (primary path)
        try:
            result = await self._llm_classify(query)
        except Exception as e:
            logger.exception("LLM classification failed")
            # Return safe default instead of fallback
            return self._default_classification(f"Classification failed: {e}")

        logger.debug(
            "LLM classification: task_complexity=%s, plan_only=%s, template_intent=%s, reasoning=%s",
            result.task_complexity,
            result.is_plan_only,
            result.template_intent,
            result.reasoning,
        )
        return result

    async def _llm_classify(self, query: str) -> UnifiedClassification:
        """Use fast LLM for unified classification."""
        from datetime import UTC, datetime

        current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        prompt = _UNIFIED_CLASSIFICATION_PROMPT.format(query=query, current_time=current_time)
        return await self._structured_model.ainvoke(prompt)

    def _default_classification(self, reason: str = "Default") -> UnifiedClassification:
        """Safe default when everything fails."""
        return UnifiedClassification(task_complexity="medium", is_plan_only=False, reasoning=reason)
