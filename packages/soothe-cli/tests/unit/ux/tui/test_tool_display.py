"""Unit tests for step-card tool activity line formatting."""

from __future__ import annotations

from soothe_sdk.client.protocol import preview_first

from soothe_cli.tui.tool_display import (
    format_step_tool_activity_command,
    format_step_tool_activity_line,
    format_step_tool_activity_status_tail,
)


def test_format_command_shows_all_present_args() -> None:
    line = format_step_tool_activity_command("grep", {"pattern": "foo", "path": "/tmp"})
    assert line.startswith("Grep(foo")
    assert "path=" in line


def test_format_command_includes_read_file_offset() -> None:
    line = format_step_tool_activity_command(
        "read_file",
        {
            "file_path": "/Users/tester/project/README.md",
            "offset": 100,
        },
    )
    assert line.startswith("ReadFile(")
    assert "offset=100" in line


def test_format_command_abbreviates_path_arg() -> None:
    line = format_step_tool_activity_command(
        "read_file",
        {"file_path": "/Users/tester/project/src/main.py"},
    )
    assert line.startswith("ReadFile(")
    assert "~/" in line or "main.py" in line
    assert "offset=" not in line


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


def test_format_command_edit_file_multiline_args_single_line() -> None:
    """edit_file old_string/new_string previews must not break activity rows."""
    old_string = "### Design Specifications\n| RFC | Title |\n|---|---|"
    new_string = "### Design Specifications\n| RFC | Title |\n|---|---|\n| [RFC-000](specs/RFC-000)"
    line = format_step_tool_activity_command(
        "edit_file",
        {
            "file_path": "/Users/tester/project/docs/user_guide.md",
            "old_string": old_string,
            "new_string": new_string,
        },
    )
    compact_old = " ".join(old_string.split())
    compact_new = " ".join(new_string.split())
    assert "\n" not in line
    assert line.startswith("EditFile(")
    assert f"new_string={preview_first(compact_new, 30)}" in line
    assert f"old_string={preview_first(compact_old, 30)}" in line
