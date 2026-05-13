"""Unit tests for streaming EventBus wire-size stats (IG-403)."""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from soothe_daemon.event_size_stats import (
    EventSizeDistributionCollector,
    _StreamingWindow,
)


def test_welford_matches_batch_statistics() -> None:
    w = _StreamingWindow()
    values = [100, 200, 350, 50, 900]
    for v in values:
        w.observe(v)
    batch_mean = sum(values) / len(values)
    batch_var = sum((x - batch_mean) ** 2 for x in values) / (len(values) - 1)
    assert w.count == len(values)
    assert w.variance() == pytest.approx(batch_var)
    line = w.format_log_line()
    assert "n=5" in line
    assert "mean=320B" in line
    assert "min=50B" in line
    assert "max=900B" in line


def test_emit_never_seen_no_log() -> None:
    c = EventSizeDistributionCollector()
    lines: list[str] = []
    assert not c.emit_log_if_active(idle_pause_seconds=120.0, log_fn=lines.append)
    assert lines == []


def test_emit_logs_and_resets_window() -> None:
    c = EventSizeDistributionCollector()
    c.record_event_dict({"type": "ping", "n": 1})
    lines: list[str] = []
    with patch("soothe_daemon.event_size_stats.time.monotonic", return_value=10.0):
        assert c.emit_log_if_active(idle_pause_seconds=120.0, log_fn=lines.append)
    assert len(lines) == 1
    assert lines[0].startswith("[event_size_stats]")
    assert "n=1" in lines[0]
    lines.clear()
    with patch("soothe_daemon.event_size_stats.time.monotonic", return_value=20.0):
        assert not c.emit_log_if_active(idle_pause_seconds=120.0, log_fn=lines.append)
    assert lines == []


def test_idle_discards_window_without_log() -> None:
    c = EventSizeDistributionCollector()
    with patch("soothe_daemon.event_size_stats.time.monotonic", return_value=0.0):
        c.record_event_dict({"type": "a"})
    lines: list[str] = []
    with patch("soothe_daemon.event_size_stats.time.monotonic", return_value=200.0):
        assert not c.emit_log_if_active(idle_pause_seconds=120.0, log_fn=lines.append)
    assert lines == []
    with patch("soothe_daemon.event_size_stats.time.monotonic", return_value=300.0):
        c.record_event_dict({"type": "b"})
    with patch("soothe_daemon.event_size_stats.time.monotonic", return_value=350.0):
        assert c.emit_log_if_active(idle_pause_seconds=120.0, log_fn=lines.append)
    assert len(lines) == 1
    assert "n=1" in lines[0]


def test_histogram_multiple_bins() -> None:
    w = _StreamingWindow()
    w.observe(50)
    w.observe(500)
    w.observe(5000)
    line = w.format_log_line()
    assert "<256B=" in line
    assert "<1KiB=" in line
    assert "<16KiB=" in line  # 5000B falls in 4Ki–16Ki bucket
    assert w.count == 3
    assert "mean=1850B" in line
    assert "max=5000B" in line


def test_stdev_zero_single_sample() -> None:
    w = _StreamingWindow()
    w.observe(42)
    assert w.variance() == 0.0
    assert math.sqrt(w.variance()) == 0.0
