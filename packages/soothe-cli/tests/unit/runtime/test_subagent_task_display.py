"""Tests for subagent task assistant display scrubbing."""

from __future__ import annotations

from soothe_cli.runtime.presentation.subagent_task_display import (
    format_subagent_task_assistant_for_display,
)


def test_deep_research_internal_json_is_suppressed() -> None:
    raw = (
        '我来帮您查询世界杯进展。{"sub_questions": [{"question": "stage?", '
        '"suggested_domain": "web"}]}{"queries": [{"query": "World Cup 2026", '
        '"domain_hint": "web"}]}'
    )
    assert format_subagent_task_assistant_for_display(raw, subagent_type="deep_research") == ""


def test_deep_research_prose_without_json_is_kept() -> None:
    raw = "Research complete: 48 teams qualified."
    assert format_subagent_task_assistant_for_display(raw, subagent_type="deep_research") == raw


def test_non_research_subagent_returns_raw_text_as_is() -> None:
    raw = '{"decision": "continue"}'
    assert format_subagent_task_assistant_for_display(raw, subagent_type="other") == raw
