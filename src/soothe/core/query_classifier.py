"""Query complexity classification for adaptive processing."""

from __future__ import annotations

import logging
import re
from typing import ClassVar

from soothe.core.classification import (
    ComplexityLevel,
    classify_by_keywords,
    count_tokens,
)

logger = logging.getLogger(__name__)


class QueryClassifier:
    """Classify query complexity for adaptive processing.

    Uses fast heuristics to determine processing requirements.
    No LLM calls to maintain sub-millisecond latency.

    Args:
        trivial_token_threshold: Max tokens for trivial queries (default: 10).
        simple_token_threshold: Max tokens for simple queries (default: 30).
        medium_token_threshold: Max tokens for medium queries (default: 60).
        use_tiktoken: Use tiktoken for token counting (default: True).
    """

    _TRIVIAL_PATTERNS: ClassVar[list[str]] = [
        r"^(hi|hello|hey|thanks|thank you|ok|yes|no|got it|sure|alright)$",
        r"^(who|what|where|when)\s+(is|are|was|were)\s+\w+\s*\??$",
    ]

    _SIMPLE_PATTERNS: ClassVar[list[str]] = [
        r".*\b(read|show|list|display|cat|open|view)\s+\w+",  # Direct file operations
        r".*\b(search|find|look up)\s+",  # Basic searches
        r".*\b(run|execute|start)\s+",  # Direct execution
    ]

    def __init__(
        self,
        trivial_token_threshold: int = 10,
        simple_token_threshold: int = 30,
        medium_token_threshold: int = 60,
        *,
        use_tiktoken: bool = True,
    ) -> None:
        """Initialize the classifier with token thresholds.

        Args:
            trivial_token_threshold: Max tokens for trivial queries.
            simple_token_threshold: Max tokens for simple queries.
            medium_token_threshold: Max tokens for medium queries.
            use_tiktoken: Use tiktoken for token counting (default: True).
        """
        self._trivial_threshold = trivial_token_threshold
        self._simple_threshold = simple_token_threshold
        self._medium_threshold = medium_token_threshold
        self._use_tiktoken = use_tiktoken

    def classify(self, query: str) -> ComplexityLevel:
        """Classify query complexity in < 1ms.

        Uses pattern matching and token count heuristics.
        No LLM calls to maintain sub-millisecond latency.

        Args:
            query: User input text.

        Returns:
            Complexity level: "trivial", "simple", "medium", or "complex".
        """
        if not query or not query.strip():
            return "simple"

        query_lower = query.lower().strip()

        # Count tokens instead of words (offline, no model needed)
        token_count = count_tokens(query, use_tiktoken=self._use_tiktoken)

        # Check keywords using shared function
        keyword_result = classify_by_keywords(query)
        if keyword_result == "complex":
            logger.debug("Query classified as complex due to keyword: %s", query[:50])
            return "complex"
        if keyword_result == "medium":
            logger.debug("Query classified as medium due to keyword: %s", query[:50])
            return "medium"

        # Check for trivial patterns
        for pattern in self._TRIVIAL_PATTERNS:
            if re.match(pattern, query_lower):
                logger.debug("Query classified as trivial due to pattern match: %s", query[:50])
                return "trivial"

        # Check for simple patterns (before token count check)
        for pattern in self._SIMPLE_PATTERNS:
            if re.match(pattern, query_lower):
                logger.debug("Query classified as simple due to pattern match: %s", query[:50])
                return "simple"

        # Token count heuristics with FIXED boundary (>= instead of >)
        # This ensures exactly N tokens is classified at the higher level
        # Examples: exactly 10 tokens -> simple (not trivial)
        #           exactly 30 tokens -> medium (not simple)
        #           exactly 60 tokens -> complex (not medium)
        if token_count >= self._medium_threshold:
            logger.debug("Query classified as complex due to token count (%d): %s", token_count, query[:50])
            return "complex"

        if token_count >= self._simple_threshold:
            logger.debug("Query classified as medium due to token count (%d): %s", token_count, query[:50])
            return "medium"

        if token_count >= self._trivial_threshold:
            logger.debug("Query classified as simple due to token count (%d): %s", token_count, query[:50])
            return "simple"

        # Default to trivial for very short queries
        logger.debug("Query classified as trivial due to short length (%d tokens): %s", token_count, query[:50])
        return "trivial"
