"""Shared complexity classification constants and utilities.

This module provides a single source of truth for complexity classification
used by both QueryClassifier (runtime optimization) and AutoPlanner (backend routing).

Architecture Decision (RFC-0010):
- QueryClassifier determines memory/context skipping (performance optimization)
- AutoPlanner determines planner backend selection (ClaudePlanner vs SubagentPlanner vs DirectPlanner)
- Both use the same keyword sets and classification logic from this shared module
- This eliminates duplication and prevents keyword drift bugs

Thresholds:
- Trivial: greetings, very short queries (<5 words)
- Simple: direct operations, basic searches (<15 words)
- Medium: multi-step tasks, planning (<30 words)
- Complex: architectural decisions (>30 words for QueryClassifier, >80 for AutoPlanner)

Note: AutoPlanner uses a higher threshold for "complex" because architectural
decisions need more context and should default to SubagentPlanner unless
explicitly complex.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

ComplexityLevel = Literal["trivial", "simple", "medium", "complex"]

# Unified complex keywords (merge QueryClassifier + AutoPlanner)
COMPLEX_KEYWORDS = frozenset(
    {
        # Architecture & Design
        "architect",
        "architecture",
        "design system",
        "system design",
        "redesign",
        "framework",
        "microservice",
        # Migration & Refactoring
        "migrate",
        "migration",
        "refactor",
        "refactor entire",
        "rewrite",
        "overhaul",
        # Strategy & Planning
        "roadmap",
        "strategy",
        "multi-phase",
        "comprehensive",
        "comprehensive plan",
        # Scale & Infrastructure
        "scale",
        "infrastructure",
        "end-to-end",
        "full-stack",
    }
)

# Unified medium keywords (from AutoPlanner)
MEDIUM_KEYWORDS = frozenset(
    {
        "plan",
        "planning",
        "implement",
        "build",
        "create feature",
        "add support",
        "integrate",
        "optimise",
        "optimize",
        "debug",
        "investigate",
        "analyse",
        "analyze",
        "review",
        "test suite",
    }
)

# Thresholds with clear documentation
DEFAULT_THRESHOLDS = {
    "trivial": 5,  # QueryClassifier: greetings, very short queries
    "simple": 15,  # Both: direct operations, basic searches
    "medium": 30,  # QueryClassifier: multi-step tasks
    "complex": 80,  # AutoPlanner: architectural decisions (higher threshold)
}


def count_words(text: str) -> int:
    """Count words with CJK awareness.

    CJK scripts (Chinese, Japanese, Korean) have no whitespace between
    characters, so str.split() returns 1 token for an entire sentence.
    Each CJK ideograph is counted as one word-equivalent so that complexity
    thresholds work correctly for non-Latin text.

    Args:
        text: Input text to count words in.

    Returns:
        Word count with CJK characters counted individually.

    Examples:
        >>> count_words("hello world")
        2
        >>> count_words("使用浏览器获取最新的美国伊朗战争信息")
        18
        >>> count_words("使用 browser 获取信息")
        7
    """
    cjk_count = sum(1 for ch in text if unicodedata.category(ch).startswith("Lo"))
    if cjk_count > 0:
        non_cjk = re.sub(
            r"[\u3040-\u309f\u30a0-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\U00020000-\U0002a6df]",
            " ",
            text,
        )
        ascii_words = len(non_cjk.split())
        return cjk_count + ascii_words
    return len(text.split())


def classify_by_keywords(text: str) -> ComplexityLevel | None:
    """Classify based on keywords only.

    Returns None if no keywords match (ambiguous, need word count).

    Args:
        text: Input text to classify.

    Returns:
        "complex", "medium", or None if no keywords match.

    Examples:
        >>> classify_by_keywords("architect a new system")
        'complex'
        >>> classify_by_keywords("create a plan for tests")
        'medium'
        >>> classify_by_keywords("hello world")
        None
    """
    text_lower = text.lower()

    if any(kw in text_lower for kw in COMPLEX_KEYWORDS):
        return "complex"

    if any(kw in text_lower for kw in MEDIUM_KEYWORDS):
        return "medium"

    return None
