"""Tests for progress wire-bridge helpers."""

from __future__ import annotations

import logging

from soothe.utils.progress import (
    emit_progress,
    get_wire_bridge,
    reset_wire_bridge,
    set_wire_bridge,
)


def test_emit_progress_uses_wire_bridge_exclusively() -> None:
    seen: list[dict[str, object]] = []

    def _sink(event: dict[str, object]) -> None:
        seen.append(event)

    token = set_wire_bridge(_sink)
    try:
        assert get_wire_bridge() is _sink
        emit_progress(
            {"type": "soothe.subagent.browser_use.step.completed", "tool_name": "Navigate"},
            logging.getLogger("test.progress"),
        )
    finally:
        reset_wire_bridge(token)

    assert len(seen) == 1
    assert seen[0]["tool_name"] == "Navigate"
    assert get_wire_bridge() is None
