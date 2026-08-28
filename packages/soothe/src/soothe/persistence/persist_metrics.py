"""Persistence latency metrics (debug logging)."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def persist_timer(operation: str, *, loop_id: str = "") -> Iterator[None]:
    """Log wall time for a persistence operation at DEBUG level."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        suffix = f" loop={loop_id}" if loop_id else ""
        logger.debug(
            "Persist %s completed in %.1fms%s",
            operation,
            elapsed_ms,
            suffix,
        )


def log_pending_loops(count: int) -> None:
    """Log coalesced pending loop count (queue depth proxy)."""
    if count > 0:
        logger.debug("Persist pending_loops=%d", count)
