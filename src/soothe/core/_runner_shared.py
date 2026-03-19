"""Shared types and helpers for SootheRunner mixins."""

from __future__ import annotations

from typing import Any

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""

_MIN_MEMORY_STORAGE_LENGTH = 50


def _custom(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk."""
    return ((), "custom", data)
