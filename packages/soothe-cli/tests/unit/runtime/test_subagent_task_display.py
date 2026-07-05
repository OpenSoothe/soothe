"""Tests for subagent task assistant display scrubbing."""

from __future__ import annotations

from soothe_cli.runtime.presentation.subagent_task_display import (
    format_subagent_task_assistant_for_display,
)


def test_tacitus_internal_json_is_suppressed() -> None:
    raw = (
        '我来帮您查询世界杯进展。{"sub_questions": [{"question": "stage?", '
        '"suggested_domain": "web"}]}{"queries": [{"query": "World Cup 2026", '
        '"domain_hint": "web"}]}'
    )
    assert format_subagent_task_assistant_for_display(raw, subagent_type="tacitus") == ""


def test_tacitus_prose_without_json_is_kept() -> None:
    raw = "Research complete: 48 teams qualified."
    assert format_subagent_task_assistant_for_display(raw, subagent_type="tacitus") == raw


def test_non_tacitus_still_uses_explore_formatter() -> None:
    raw = '{"decision": "continue"}'
    assert format_subagent_task_assistant_for_display(raw, subagent_type="explore") == ""
