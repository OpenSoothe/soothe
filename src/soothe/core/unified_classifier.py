"""Unified LLM-based classification system.

This module provides a single classification system that replaces all keyword-based
classification with intelligent LLM-based analysis. It makes one fast LLM call per
query to determine:

1. Runtime complexity (for memory/context optimization)
2. Planner complexity (for backend selection)
3. Plan-only intent (for execution control)

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
_TOKEN_THRESHOLD_RUNTIME_MEDIUM = 30
_TOKEN_THRESHOLD_RUNTIME_COMPLEX = 60
_TOKEN_THRESHOLD_PLANNER_MEDIUM = 30
_TOKEN_THRESHOLD_PLANNER_COMPLEX = 160


class UnifiedClassification(BaseModel):
    """Result of unified LLM classification."""

    runtime_complexity: Literal["simple", "medium", "complex"] = Field(
        description="Query complexity for runtime optimization (trivial merged into simple)"
    )
    planner_complexity: Literal["simple", "medium", "complex"] = Field(
        description="Query complexity for planner backend selection"
    )
    is_plan_only: bool = Field(description="True if user only wants planning without execution")
    reasoning: str | None = Field(default=None, description="Brief explanation of classification decisions")


_UNIFIED_CLASSIFICATION_PROMPT = """\
Analyze this user request and classify it for routing decisions.

User request: {query}

Provide classifications in JSON format with these fields:

1. "runtime_complexity": One of "simple", "medium", "complex"
   - simple: Greetings, direct operations, basic searches, short queries
   - medium: Multi-step tasks, debugging, code review, planning
   - complex: Architectural decisions, migrations, large-scale refactoring

2. "planner_complexity": One of "simple", "medium", "complex"
   - simple: Single-step tasks, direct operations
   - medium: Multi-step implementation, debugging, review
   - complex: Architecture design, migration, large refactoring

3. "is_plan_only": true or false
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
                "LLM classification: runtime=%s, planner=%s, plan_only=%s",
                result.runtime_complexity,
                result.planner_complexity,
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

        # Runtime complexity (merged trivial into simple)
        if token_count >= _TOKEN_THRESHOLD_RUNTIME_COMPLEX:
            runtime = "complex"
        elif token_count >= _TOKEN_THRESHOLD_RUNTIME_MEDIUM:
            runtime = "medium"
        else:
            runtime = "simple"  # All queries < 30 tokens

        # Planner complexity
        if token_count >= _TOKEN_THRESHOLD_PLANNER_COMPLEX:
            planner = "complex"
        elif token_count >= _TOKEN_THRESHOLD_PLANNER_MEDIUM:
            planner = "medium"
        else:
            planner = "simple"

        # Plan-only detection (simple heuristic)
        query_lower = query.lower().strip()
        is_plan = (
            "plan only" in query_lower
            or "only plan" in query_lower
            or query_lower.startswith(("create a plan", "make a plan"))
        )

        return UnifiedClassification(
            runtime_complexity=runtime,
            planner_complexity=planner,
            is_plan_only=is_plan,
            reasoning=f"Fallback: {token_count} tokens",
        )

    def _default_classification(self, reason: str = "Default") -> UnifiedClassification:
        """Safe default when everything fails."""
        return UnifiedClassification(
            runtime_complexity="medium", planner_complexity="medium", is_plan_only=False, reasoning=reason
        )
