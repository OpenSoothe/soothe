"""Unit tests for step-card tool activity line formatting."""

from __future__ import annotations

from soothe_cli.tui.tool_display import (
    format_step_tool_activity_command,
    format_step_tool_activity_line,
    format_step_tool_activity_status_tail,
)


def test_format_command_uses_meta_arg_keys() -> None:
    line = format_step_tool_activity_command("grep", {"pattern": "foo", "path": "/tmp"})
    assert line == "Grep(foo)"


def test_format_command_abbreviates_path_arg() -> None:
    line = format_step_tool_activity_command(
        "read_file",
        {"file_path": "/Users/tester/project/src/main.py"},
    )
    assert line.startswith("ReadFile(")
    assert "~/" in line or "main.py" in line


def test_format_command_without_args_is_display_name_only() -> None:
    assert format_step_tool_activity_command("grep", {}) == "Grep"


def test_format_status_tail_success_duration() -> None:
    assert format_step_tool_activity_status_tail("success", duration_ms=3200) == " (3.2s)"


def test_format_activity_line_combines_command_and_tail() -> None:
    line = format_step_tool_activity_line(
        "glob",
        {"pattern": "**/*.py"},
        "running",
    )
    assert line == "Glob(**/*.py) · running"
