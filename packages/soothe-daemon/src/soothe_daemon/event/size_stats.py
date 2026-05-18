"""Streaming event wire-size distribution for the daemon EventBus (IG-403).

Uses fixed-bin histogram + Welford's online mean/variance — O(1) memory per window.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from typing import Any

from soothe_sdk.client.protocol import encode

logger = logging.getLogger(__name__)

# Upper bounds (bytes, exclusive) for histogram bins; overflow is the last bucket.
_BIN_UPPER_BYTES: tuple[int, ...] = (
    256,
    1024,
    4096,
    16384,
    65536,
    262_144,
    1_048_576,
    4_194_304,
    16_777_216,
)


def _bin_label_for_index(idx: int) -> str:
    if idx >= len(_BIN_UPPER_BYTES):
        return f">={_BIN_UPPER_BYTES[-1]}B"
    upper = _BIN_UPPER_BYTES[idx]
    if upper < 1024:
        return f"<{upper}B"
    if upper < 1024 * 1024:
        return f"<{upper // 1024}KiB"
    return f"<{upper // (1024 * 1024)}MiB"


class _StreamingWindow:
    """Single reporting window: histogram + min/max + Welford moments."""

    __slots__ = ("_counts", "_n", "_mean", "_m2", "_min", "_max")

    def __init__(self) -> None:
        self._counts = [0] * (len(_BIN_UPPER_BYTES) + 1)
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0
        self._min = 0
        self._max = 0

    def reset(self) -> None:
        self._counts = [0] * (len(_BIN_UPPER_BYTES) + 1)
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0
        self._min = 0
        self._max = 0

    @property
    def count(self) -> int:
        return self._n

    def observe(self, size: int) -> None:
        if size < 0:
            size = 0
        idx = 0
        for i, edge in enumerate(_BIN_UPPER_BYTES):
            if size < edge:
                idx = i
                break
        else:
            idx = len(_BIN_UPPER_BYTES)
        self._counts[idx] += 1

        self._n += 1
        if self._n == 1:
            self._min = size
            self._max = size
        else:
            self._min = min(self._min, size)
            self._max = max(self._max, size)

        delta = float(size) - self._mean
        self._mean += delta / self._n
        delta2 = float(size) - self._mean
        self._m2 += delta * delta2

    def variance(self) -> float:
        if self._n < 2:
            return 0.0
        return self._m2 / float(self._n - 1)

    def format_log_line(self) -> str:
        n = self._n
        if n == 0:
            return ""
        stdev = math.sqrt(self.variance())
        parts = [
            f"n={n}",
            f"mean={self._mean:.0f}B",
            f"stdev={stdev:.0f}B",
            f"min={self._min}B",
            f"max={self._max}B",
        ]
        for i, c in enumerate(self._counts):
            if c == 0:
                continue
            pct = 100.0 * c / n
            parts.append(f"{_bin_label_for_index(idx=i)}={pct:.1f}%")
        return "[event_size_stats] " + " ".join(parts)


class EventSizeDistributionCollector:
    """Thread-safe collector: records wire sizes and emits periodic log summaries."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._window = _StreamingWindow()
        self._last_event_mono = 0.0

    def record_event_dict(self, event: dict[str, Any]) -> None:
        """Record one published event using the same encoding as the IPC wire format."""
        try:
            raw = encode(event).rstrip(b"\n")
            size = len(raw)
        except Exception:
            logger.debug("event_size_stats: failed to measure event size", exc_info=True)
            return
        with self._lock:
            self._last_event_mono = time.monotonic()
            self._window.observe(size)

    def emit_log_if_active(
        self,
        *,
        idle_pause_seconds: float,
        log_fn: Callable[[str], None],
    ) -> bool:
        """Log the current window if there was traffic and the bus is not idle.

        If idle for ``idle_pause_seconds``, discards the window without logging.

        Returns:
            True if a log line was emitted.
        """
        now = time.monotonic()
        with self._lock:
            if self._last_event_mono == 0.0:
                return False
            if now - self._last_event_mono >= idle_pause_seconds:
                self._window.reset()
                return False
            if self._window.count == 0:
                return False
            line = self._window.format_log_line()
            self._window.reset()
        if line:
            log_fn(line)
            return True
        return False
