"""Query complexity classification for adaptive processing."""

from __future__ import annotations

import logging
import re
from typing import ClassVar, Literal

logger = logging.getLogger(__name__)

ComplexityLevel = Literal["trivial", "simple", "medium", "complex"]


class QueryClassifier:
    """Classify query complexity for adaptive processing.

    Uses fast heuristics to determine processing requirements.
    No LLM calls to maintain sub-millisecond latency.

    Args:
        trivial_word_threshold: Max words for trivial queries (default: 5).
        simple_word_threshold: Max words for simple queries (default: 15).
        medium_word_threshold: Max words for medium queries (default: 30).
    """

    _TRIVIAL_PATTERNS: ClassVar[list[str]] = [
        r"^(hi|hello|hey|thanks|thank you|ok|yes|no|got it|sure|alright)$",
        r"^(who|what|where|when)\s+(is|are|was|were)\s+\w+\s*\??$",
    ]

    _SIMPLE_PATTERNS: ClassVar[list[str]] = [
        r"^(read|show|list|display|cat|open|view)\s+\w+",  # Direct file operations
        r"^(search|find|look up)\s+",  # Basic searches
        r"^(run|execute|start)\s+",  # Direct execution
    ]

    _COMPLEX_KEYWORDS = frozenset(
        [
            "architect",
            "architecture",
            "design system",
            "migrate",
            "migration",
            "refactor",
            "redesign",
            "rewrite",
            "overhaul",
            "scale",
            "multi-phase",
            "roadmap",
            "strategy",
            "comprehensive",
            "end-to-end",
            "full-stack",
            "infrastructure",
            "system design",
            "framework",
            "microservice",
        ]
    )

    def __init__(
        self,
        trivial_word_threshold: int = 5,
        simple_word_threshold: int = 15,
        medium_word_threshold: int = 30,
    ) -> None:
        """Initialize the classifier with configurable thresholds.

        Args:
            trivial_word_threshold: Max words for trivial queries.
            simple_word_threshold: Max words for simple queries.
            medium_word_threshold: Max words for medium queries.
        """
        self._trivial_threshold = trivial_word_threshold
        self._simple_threshold = simple_word_threshold
        self._medium_threshold = medium_word_threshold

    def classify(self, query: str) -> ComplexityLevel:
        """Classify query complexity in < 1ms.

        Uses pattern matching and word count heuristics.
        No LLM calls to maintain sub-millisecond latency.

        Args:
            query: User input text.

        Returns:
            Complexity level: "trivial", "simple", "medium", or "complex".
        """
        if not query or not query.strip():
            return "simple"

        query_lower = query.lower().strip()
        word_count = len(query.split())

        # Check for complex keywords (highest priority)
        if any(kw in query_lower for kw in self._COMPLEX_KEYWORDS):
            logger.debug("Query classified as complex due to keyword: %s", query[:50])
            return "complex"

        # Check for trivial patterns
        for pattern in self._TRIVIAL_PATTERNS:
            if re.match(pattern, query_lower):
                logger.debug("Query classified as trivial due to pattern match: %s", query[:50])
                return "trivial"

        # Word count heuristics
        if word_count > self._medium_threshold:
            logger.debug("Query classified as complex due to word count (%d): %s", word_count, query[:50])
            return "complex"

        if word_count > self._simple_threshold:
            logger.debug("Query classified as medium due to word count (%d): %s", word_count, query[:50])
            return "medium"

        if word_count > self._trivial_threshold:
            # Check for simple patterns
            for pattern in self._SIMPLE_PATTERNS:
                if re.match(pattern, query_lower):
                    logger.debug("Query classified as simple due to pattern match: %s", query[:50])
                    return "simple"
            return "medium"

        # Default to trivial for very short queries
        if word_count <= self._trivial_threshold:
            logger.debug("Query classified as trivial due to short length (%d words): %s", word_count, query[:50])
            return "trivial"

        return "simple"
