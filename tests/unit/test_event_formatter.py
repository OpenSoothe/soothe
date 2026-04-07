"""Tests for shared event summary formatting (TUI / registry templates)."""

from __future__ import annotations

from soothe.ux.shared.event_formatter import build_event_summary


def test_loop_completed_uses_completion_summary_when_set() -> None:
    line = build_event_summary(
        "soothe.agentic.loop.completed",
        {
            "completion_summary": "已完成翻译",
            "evidence_summary": "noise",
            "total_steps": 1,
        },
    )
    assert line == "Done: 已完成翻译"


def test_loop_completed_defaults_completion_summary_from_evidence() -> None:
    line = build_event_summary(
        "soothe.agentic.loop.completed",
        {
            "evidence_summary": "Step step_0: ok",
        },
    )
    assert line == "Done: Step step_0: ok"


def test_loop_completed_fallback_complete_when_empty() -> None:
    line = build_event_summary(
        "soothe.agentic.loop.completed",
        {},
    )
    assert line == "Done: complete"
