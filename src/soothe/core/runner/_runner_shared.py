"""Shared types and helpers for SootheRunner mixins."""

from __future__ import annotations

import logging
from typing import Any

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""

_MIN_MEMORY_STORAGE_LENGTH = 50

_logger = logging.getLogger(__name__)


def _custom(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk."""
    return ((), "custom", data)


def _validate_goal(goal: str | None, user_input: str) -> str:
    """Ensure goal is never empty or just punctuation.

    Args:
        goal: The plan goal from planner.
        user_input: Original user input as fallback.

    Returns:
        Validated goal string.
    """
    if not goal or goal.strip() in {":", ""}:
        _logger.warning("Empty or invalid goal detected, using user input")
        return user_input or "Unnamed goal"
    return goal.strip()
