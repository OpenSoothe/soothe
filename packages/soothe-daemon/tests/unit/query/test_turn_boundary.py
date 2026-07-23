"""Unit tests for daemon turn_id helper (IG-616)."""

from __future__ import annotations

from soothe_daemon.query.turn_boundary import format_turn_id


def test_format_turn_id() -> None:
    assert format_turn_id("loop-x", 2) == "loop-x:2"
    assert format_turn_id("  ", 1) == ""
    assert format_turn_id("loop-x", 0) == ""
