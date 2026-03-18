"""Shared complexity classification constants and utilities.

This module provides a single source of truth for complexity classification
used by both QueryClassifier (runtime optimization) and AutoPlanner (backend routing).

Architecture Decision (RFC-0010):
- QueryClassifier determines memory/context skipping (performance optimization)
- AutoPlanner determines planner backend selection (ClaudePlanner vs SubagentPlanner vs DirectPlanner)
- Both use the same keyword sets and classification logic from this shared module
- This eliminates duplication and prevents keyword drift bugs

Thresholds (token-based):
- Trivial: greetings, very short queries (<10 tokens)
- Simple: direct operations, basic searches (<30 tokens)
- Medium: multi-step tasks, planning (<60 tokens)
- Complex: architectural decisions (>=60 tokens for QueryClassifier, >=160 for AutoPlanner)

Note: AutoPlanner uses a higher threshold for "complex" because architectural
decisions need more context and should default to SubagentPlanner unless
explicitly complex.
"""

from __future__ import annotations

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

_PLAN_ONLY_PATTERNS = (
    r"^\s*create\s+(?:a\s+)?plan\b",
    r"^\s*make\s+(?:a\s+)?plan\b",
    r"^\s*draft\s+(?:a\s+)?plan\b",
    r"^\s*write\s+(?:a\s+)?plan\b",
)


def count_tokens(text: str, *, use_tiktoken: bool = True) -> int:
    """Count tokens using offline tokenizers.

    Priority:
    1. tiktoken (cl100k_base encoding) if available - most accurate
    2. Estimation (len // 4) as fallback - zero dependency

    Args:
        text: Text to count tokens for.
        use_tiktoken: Try to use tiktoken if available (default: True).

    Returns:
        Estimated token count.

    Examples:
        >>> count_tokens("Hello world")  # With tiktoken
        2
        >>> count_tokens("Hello world", use_tiktoken=False)
        3  # Estimation: len("Hello world") // 4
    """
    # Try tiktoken first (most accurate offline)
    if use_tiktoken:
        try:
            import tiktoken

            # cl100k_base is used by GPT-4, Claude, and most modern LLMs
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except ImportError:
            pass  # Fall through to estimation

    # Fallback: simple estimation (very fast)
    return len(text) // 4


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


def is_plan_only_request(text: str) -> bool:
    """Return True when the user asks for planning output only.

    This detects explicit *plan creation* phrasing and suppresses execution
    of generated steps in the runner.
    """
    import re

    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    if any(re.match(pattern, normalized) for pattern in _PLAN_ONLY_PATTERNS):
        return True

    return "plan only" in normalized or "only plan" in normalized
