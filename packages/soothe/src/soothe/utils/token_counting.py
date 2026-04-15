"""Token counting utilities.

This module provides utilities for counting tokens in text.
"""

from __future__ import annotations

from typing import Literal

ComplexityLevel = Literal["simple", "medium", "complex"]  # Simplified: merged trivial into simple


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
