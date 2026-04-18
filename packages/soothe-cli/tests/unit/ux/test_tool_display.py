"""Tests for TUI tool header formatting (``format_tool_display``)."""

from __future__ import annotations

from soothe_cli.tui.tool_display import format_tool_display


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


def test_read_file_accepts_path_name() -> None:
    s = format_tool_display("read_file", {"path_name": "/x/README.md"})
    assert "README" in s


def test_grep_accepts_regex_alias() -> None:
    s = format_tool_display("grep", {"regex": "TODO"})
    assert "TODO" in s


def test_fallback_shows_kv_when_unknown_tool() -> None:
    s = format_tool_display("custom_tool", {"x": 1})
    assert "x=" in s
