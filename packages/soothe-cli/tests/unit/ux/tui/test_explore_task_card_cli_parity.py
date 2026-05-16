"""Explore Task tool card notes aligned with CLI stderr (IG-342)."""

from __future__ import annotations

from soothe_cli.tui.textual_adapter import _format_task_scoped_tool_invocation_line


def test_task_scoped_tool_invocation_line_includes_task_prefix() -> None:
    """Mirrors Task subgraph tool line prefix (⚙ Task(type):#N …)."""
    line = _format_task_scoped_tool_invocation_line(
        ("functions.task:2", "explore", "LEN-02"),
        "glob",
        {"glob_pattern": "**/*.py"},
    )
    assert line.startswith("⚙ ")
    assert "Task(explore):#2" in line
