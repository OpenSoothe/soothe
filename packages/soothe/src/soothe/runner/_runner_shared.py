"""Shared types and helpers for SootheRunner mixins."""

from __future__ import annotations

import logging
from typing import Any

from soothe.events import StreamChunk

_MIN_MEMORY_STORAGE_LENGTH = 50

_logger = logging.getLogger(__name__)


def _custom(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk."""
    return ((), "custom", data)
