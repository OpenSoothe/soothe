"""Tests for compact Task subgraph labels (IG-334)."""

from __future__ import annotations

from soothe_cli.cli.stream.task_scope import (
    brief_task_tool_call_id,
    format_task_scope_prefix,
    format_task_subagent_line,
)


def test_brief_task_tool_call_id_numeric_tail() -> None:
    assert brief_task_tool_call_id("functions.task:0") == "#0"
    assert brief_task_tool_call_id("call:42") == "#42"


def test_brief_task_tool_call_id_long_opaque() -> None:
    long_id = "x" * 30
    assert brief_task_tool_call_id(long_id) == "x" * 8


def test_format_task_scope_prefix() -> None:
    assert format_task_scope_prefix("functions.task:0", "explore") == "Task(explore):#0"


def test_format_task_subagent_line_escapes() -> None:
    s = format_task_subagent_line("explore", 'say "hi"')
    assert s == r'Task(explore, "say \"hi\"")'
