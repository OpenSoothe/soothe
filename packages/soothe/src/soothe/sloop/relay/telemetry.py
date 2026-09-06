"""In-process telemetry counters for the interrupt relay.

Not durable — resets when the relay is reconstructed. The caller can snapshot
these periodically for external export (Langfuse, statsd, Prometheus).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any


class RelayTelemetry:
    """In-process counters and latency histograms."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._latencies: dict[str, list[float]] = defaultdict(list)

    def increment(self, name: str) -> None:
        self._counters[name] += 1

    def record_latency(self, name: str, seconds: float) -> None:
        self._latencies[name].append(seconds)
        if len(self._latencies[name]) > 100:
            self._latencies[name] = self._latencies[name][-50:]

    def snapshot(self) -> dict[str, Any]:
        latencies: dict[str, dict[str, float]] = {}
        for name, values in self._latencies.items():
            if values:
                latencies[name] = {
                    "count": len(values),
                    "avg": sum(values) / len(values),
                    "min": min(values),
                    "max": max(values),
                }
        return {"counters": dict(self._counters), "latencies": latencies}

    def reset(self) -> None:
        self._counters.clear()
        self._latencies.clear()


def _now_ms() -> float:
    return datetime.now(UTC).timestamp() * 1000


def make_latency_recorder(telemetry: RelayTelemetry, metric_name: str) -> Callable[[], None]:
    """Return a closure that records elapsed time since creation."""
    start = _now_ms()

    def _record() -> None:
        telemetry.record_latency(metric_name, _now_ms() - start)

    return _record


__all__ = ["RelayTelemetry", "make_latency_recorder"]
