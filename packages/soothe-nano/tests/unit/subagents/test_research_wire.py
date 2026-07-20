"""Tests for shared research subagent wire emitter."""

from __future__ import annotations

import logging
from typing import Any

from soothe_nano.subagents.research_wire import ResearchWireEmitter


class _FakeProgress:
    def __init__(
        self,
        *,
        phase: str,
        message: str,
        loop_count: int,
        total_loops: int,
    ) -> None:
        self.phase = phase
        self.message = message
        self.loop_count = loop_count
        self.total_loops = total_loops

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "soothe.subagent.test.progress",
            "phase": self.phase,
            "message": self.message,
            "loop_count": self.loop_count,
            "total_loops": self.total_loops,
        }


class _FakeStep:
    def __init__(self, *, tool_name: str, args_preview: str, duration_ms: int) -> None:
        self.tool_name = tool_name
        self.args_preview = args_preview
        self.duration_ms = duration_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "soothe.subagent.test.step.completed",
            "tool_name": self.tool_name,
            "args_preview": self.args_preview,
            "duration_ms": self.duration_ms,
        }


def test_research_wire_emitter_calls_subagent_emit(monkeypatch: Any) -> None:
    emitted: list[dict[str, Any]] = []

    def _capture(event: dict[str, Any], _logger: logging.Logger) -> None:
        emitted.append(event)

    monkeypatch.setattr(
        "soothe_nano.subagents.research_wire.emit_subagent_wire_event",
        _capture,
    )
    emitter = ResearchWireEmitter(
        progress_event_type=_FakeProgress,
        step_event_type=_FakeStep,
        logger=logging.getLogger("test"),
    )
    emitter.progress("gather", "Searching", loop_count=1, total_loops=3)
    emitter.step("WebSearch", "query → 5 hits", duration_ms=120)

    assert len(emitted) == 2
    assert emitted[0]["phase"] == "gather"
    assert emitted[1]["tool_name"] == "WebSearch"
