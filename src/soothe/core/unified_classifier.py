"""Unified LLM-based classification system.

This module provides a single classification system that replaces all keyword-based
classification with intelligent LLM-based analysis. It makes one fast LLM call per
query to determine:

1. Task complexity (for routing and optimization)
2. Plan-only intent (for execution control)

Architecture Decision (RFC-0012):
- Single LLM call provides all classifications at once
- Eliminates keyword maintenance burden
- Handles multilingual and nuanced queries
- Falls back to token-count heuristics if LLM unavailable
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from soothe.core.classification import count_tokens

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

# Token count thresholds for fallback classification
_TOKEN_THRESHOLD_MEDIUM = 30
_TOKEN_THRESHOLD_COMPLEX = 160


class UnifiedClassification(BaseModel):
    """Result of unified LLM classification."""

    task_complexity: Literal["chitchat", "medium", "complex"] = Field(
        description="Query complexity for routing: chitchat (direct LLM), medium (subagent), complex (Claude)"
    )
    is_plan_only: bool = Field(description="True if user only wants planning without execution")
    reasoning: str | None = Field(default=None, description="Brief explanation of classification")


_UNIFIED_CLASSIFICATION_PROMPT = """\
Analyze this user request and classify it for routing decisions.

User request: {query}

Provide classifications in JSON format with these fields:

1. "task_complexity": One of "chitchat", "medium", "complex"
   - chitchat: Greetings, simple questions, short queries (< 30 tokens) - NO planning, NO context/memory
   - medium: Multi-step tasks, debugging, code review, planning (90% of tasks)
   - complex: Architecture design, migrations, large refactoring (10% of tasks)

2. "is_plan_only": true or false
   - true: User explicitly requests planning without execution
   - false: User expects both planning and execution

Respond with only valid JSON, no additional text.
"""


class UnifiedClassifier:
    """Unified LLM-based classification system.

    Replaces all keyword-based classification with a single fast LLM call.

    Args:
        fast_model: Fast LLM for classification (e.g., gpt-4o-mini).
        classification_mode: "llm", "fallback", or "disabled".
        use_tiktoken: Use tiktoken for fallback token counting.
    """

    def __init__(
        self,
        fast_model: BaseChatModel | None = None,
        classification_mode: Literal["llm", "fallback", "disabled"] = "llm",
        *,
        use_tiktoken: bool = True,
    ) -> None:
        """Initialize the unified classifier.

        Args:
            fast_model: Fast LLM for classification (e.g., gpt-4o-mini).
            classification_mode: "llm", "fallback", or "disabled".
            use_tiktoken: Use tiktoken for fallback token counting.
        """
        self._fast_model = fast_model
        self._mode = classification_mode
        self._use_tiktoken = use_tiktoken

        # Use structured output if model available
        if fast_model:
            self._structured_model = fast_model.with_structured_output(UnifiedClassification)
        else:
            self._structured_model = None

    async def classify(self, query: str) -> UnifiedClassification:
        """Classify query for routing decisions.

        Single LLM call returns all needed classifications.
        Falls back to token-count heuristics if LLM fails.

        Args:
            query: User input text.

        Returns:
            UnifiedClassification with all routing decisions.
        """
        # Disabled mode
        if self._mode == "disabled":
            return self._default_classification("Classification disabled")

        # Fallback mode (no LLM)
        if self._mode == "fallback" or not self._fast_model:
            return self._token_count_fallback(query)

        # LLM mode (primary)
        try:
            result = await self._llm_classify(query)
        except Exception as e:
            logger.warning("LLM classification failed, using fallback: %s", e)
            return self._token_count_fallback(query)
        else:
            logger.debug(
                "LLM classification: task_complexity=%s, plan_only=%s",
                result.task_complexity,
                result.is_plan_only,
            )
            return result

    async def _llm_classify(self, query: str) -> UnifiedClassification:
        """Use fast LLM for unified classification."""
        prompt = _UNIFIED_CLASSIFICATION_PROMPT.format(query=query)
        return await self._structured_model.ainvoke(prompt)

    def _token_count_fallback(self, query: str) -> UnifiedClassification:
        """Token-count based fallback (NO keywords)."""
        token_count = count_tokens(query, use_tiktoken=self._use_tiktoken)

        # Task complexity based on token count
        if token_count >= _TOKEN_THRESHOLD_COMPLEX:
            task_complexity = "complex"
        elif token_count >= _TOKEN_THRESHOLD_MEDIUM:
            task_complexity = "medium"
        else:
            task_complexity = "chitchat"  # All queries < 30 tokens

        # Plan-only detection (simple heuristic)
        query_lower = query.lower().strip()
        is_plan = (
            "plan only" in query_lower
            or "only plan" in query_lower
            or query_lower.startswith(("create a plan", "make a plan"))
        )

        return UnifiedClassification(
            task_complexity=task_complexity,
            is_plan_only=is_plan,
            reasoning=f"Fallback: {token_count} tokens",
        )

    def _default_classification(self, reason: str = "Default") -> UnifiedClassification:
        """Safe default when everything fails."""
        return UnifiedClassification(task_complexity="medium", is_plan_only=False, reasoning=reason)
