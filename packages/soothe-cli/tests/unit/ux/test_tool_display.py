"""Tests for TUI tool header formatting (``format_tool_display``)."""

from __future__ import annotations

from soothe_cli.tui.tool_display import format_tool_display
from soothe_cli.tui.widgets.messages import ToolCallMessage


def test_read_file_accepts_pascal_case_and_file_path() -> None:
    s = format_tool_display("ReadFile", {"file_path": "/tmp/README.md"})
    assert "README.md" in s
    assert "ReadFile" in s


def test_ls_accepts_directory_key() -> None:
    s = format_tool_display("ls", {"directory": "/tmp/proj"})
    assert "proj" in s or "tmp" in s


def test_ls_accepts_path_key() -> None:
    s = format_tool_display("ls", {"path": "src"})
    assert "src" in s


def test_ls_accepts_path_name() -> None:
    s = format_tool_display("ls", {"path_name": "/proj/src"})
    assert "src" in s or "proj" in s


def test_ls_shows_dot_when_path_is_cwd() -> None:
    """Listing ``.`` must not collapse to bare ls() — show explicit (.) ."""
    s = format_tool_display("ls", {"path": "."})
    assert "(.)" in s


def test_glob_shows_directory_when_pattern_absent() -> None:
    s = format_tool_display("glob", {"directory": "/tmp/proj"})
    assert "dir=" in s and ("tmp" in s or "proj" in s)


def test_read_file_accepts_path_name() -> None:
    s = format_tool_display("read_file", {"path_name": "/x/README.md"})
    assert "README" in s


def test_grep_accepts_regex_alias() -> None:
    s = format_tool_display("grep", {"regex": "TODO"})
    assert "TODO" in s


def test_fallback_shows_kv_when_unknown_tool() -> None:
    s = format_tool_display("custom_tool", {"x": 1})
    assert "x=" in s


def test_read_file_unwraps_nested_args_envelope() -> None:
    """Some transports nest kwargs under ``args``; header must still show the path."""
    s = format_tool_display("read_file", {"args": {"file_path": "/tmp/README.md"}})
    assert "README.md" in s


def test_read_file_without_path_key_shows_other_args_not_placeholder() -> None:
    """Unknown path keys used to fall through and collapse to read_file(…) (IG-219)."""
    s = format_tool_display("read_file", {"start_line": 1, "end_line": 10, "encoding": "utf-8"})
    assert "(…)" not in s
    assert "start_line=" in s or "1" in s


def test_tool_call_message_infers_name_from_tool_call_id() -> None:
    w = ToolCallMessage("tool", {}, tool_call_id="functions.glob:2", id="x")
    assert w._tool_name == "glob"


def test_ls_empty_args_shows_workspace_default_not_bare_parens() -> None:
    s = format_tool_display("ls", {})
    assert "(.)" in s


def test_glob_empty_args_shows_default_pattern_hint() -> None:
    s = format_tool_display("glob", {})
    assert "*" in s


def test_unknown_tool_empty_args_shows_ellipsis_not_bare_parens() -> None:
    s = format_tool_display("custom_tool", {})
    assert "(…)" in s


def test_task_shows_type_in_parentheses_not_brackets() -> None:
    s = format_tool_display(
        "task",
        {"subagent_type": "general-purpose", "description": "Do the thing"},
    )
    assert "[" not in s
    assert "general-purpose" in s
    assert "Do the thing" in s
    assert "(" in s and ")" in s


def test_task_type_only_uses_parentheses() -> None:
    s = format_tool_display("task", {"subagent_type": "browser"})
    assert "[" not in s
    assert "browser" in s
