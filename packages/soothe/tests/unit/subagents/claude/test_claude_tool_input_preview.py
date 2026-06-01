"""Tests for Claude tool-use argument preview (IG-219)."""

from __future__ import annotations

from soothe.subagents.claude.implementation import _preview_claude_tool_input


def test_preview_none_is_ellipsis() -> None:
    assert _preview_claude_tool_input(None) == "…"


def test_preview_empty_dict() -> None:
    assert _preview_claude_tool_input({}) == "…"


def test_preview_dict_shows_key_value_pairs() -> None:
    out = _preview_claude_tool_input({"file_path": "/tmp/x.md", "limit": 10})
    assert "file_path=" in out
    assert "x.md" in out
    assert "limit=" in out


def test_preview_long_string_truncated() -> None:
    long = "word " * 50
    out = _preview_claude_tool_input(long)
    assert len(out) <= 120
    assert out.endswith("…")
