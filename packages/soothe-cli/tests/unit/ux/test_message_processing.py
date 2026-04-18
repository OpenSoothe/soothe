"""Test message processing utilities (see IG-053).

Tests for whitespace normalization and internal tag stripping.
"""

from __future__ import annotations

from typing import Any

from soothe_cli.shared.message_processing import (
    accumulate_tool_call_chunks,
    coerce_tool_call_args_to_dict,
    format_tool_call_args,
    strip_internal_tags,
    try_parse_pending_tool_call_args,
)


class TestAccumulateToolCallChunks:
    """Streaming tool_call_chunks accumulation (IG-053)."""

    def test_dict_args_on_first_chunk_serializes_for_parse(self) -> None:
        """When the first chunk carries args as a dict, briefs/cards can resolve."""
        pending: dict[str, Any] = {}
        accumulate_tool_call_chunks(
            pending,
            [
                {
                    "id": "call-dict",
                    "name": "read_file",
                    "args": {"path": "/tmp/a.txt"},
                }
            ],
        )
        parsed = try_parse_pending_tool_call_args(pending["call-dict"])
        assert parsed == {"path": "/tmp/a.txt"}


class TestFormatToolCallArgs:
    """Display strings for tool call arguments (see IG-053)."""

    def test_pascal_case_tool_name_maps_to_arg_display(self) -> None:
        """Model may emit PascalCase names; lookup uses snake_case map."""
        assert (
            format_tool_call_args(
                "ReadFile",
                {"args": {"path": "README.md"}},
            )
            == "README.md"
        )

    def test_snake_case_unchanged(self) -> None:
        assert (
            format_tool_call_args(
                "read_file",
                {"args": {"path": "x.txt"}},
            )
            == "x.txt"
        )

    def test_fallback_when_mapped_keys_missing(self) -> None:
        """If the model uses different parameter names, show raw values."""
        # Path conversion will convert /tmp to actual OS path and abbreviate
        result = format_tool_call_args("ls", {"args": {"directory": "/tmp"}})
        # Should show some form of /tmp (may be converted or abbreviated)
        assert "tmp" in result or "/private/tmp" in result

    def test_deepagents_read_file_uses_file_path(self) -> None:
        """Filesystem middleware passes ``file_path``, not ``path``."""
        result = format_tool_call_args(
            "read_file",
            {"args": {"file_path": "/README.md"}},
        )
        # Path conversion will convert /README.md to actual OS path and abbreviate
        assert "README.md" in result

    def test_string_json_args_from_tool_call_chunk(self) -> None:
        """Streaming chunks encode args as JSON text."""
        raw = '{"file_path": "/pyproject.toml"}'
        assert coerce_tool_call_args_to_dict(raw) == {"file_path": "/pyproject.toml"}
        result = format_tool_call_args("read_file", {"args": raw})
        # Path conversion will convert /pyproject.toml to actual OS path and abbreviate
        assert "pyproject.toml" in result


class TestStripInternalTags:
    """Test whitespace normalization in strip_internal_tags()."""

    def test_preserves_spaces_between_words(self):
        """Ensure spaces are preserved between words."""
        text = "Hello world this is a test"
        result = strip_internal_tags(text)
        assert result == "Hello world this is a test"

    def test_normalizes_excessive_spaces(self):
        """Three or more spaces should collapse to single space."""
        text = "Hello      world    test"  # 6 spaces, then 4 spaces
        result = strip_internal_tags(text)
        assert result == "Hello world test"  # 6->1, 4->1

    def test_preserves_punctuation_as_is(self):
        """Punctuation spacing is preserved as-is for streaming."""
        text = "First sentence.Second sentence.Third one"
        result = strip_internal_tags(text)
        # We no longer auto-add spaces after punctuation (was causing streaming bugs)
        assert result == "First sentence.Second sentence.Third one"

    def test_removes_search_data_tags(self):
        """Remove <search_data> tags and content."""
        text = "Before <search_data>content</search_data> After"
        result = strip_internal_tags(text)
        assert result == "Before After"

    def test_removes_search_data_tags_no_spaces(self):
        """Remove <search_data> tags when no surrounding spaces."""
        text = "Before<search_data>content</search_data>After"
        result = strip_internal_tags(text)
        # No spaces before/after tags means no space in result
        assert result == "BeforeAfter"

    def test_complex_formatting_preserved(self):
        """Test complex markdown formatting is preserved."""
        text = "**Bold text** here.More text after."
        result = strip_internal_tags(text)
        # Punctuation spacing preserved as-is (no auto-correction)
        assert result == "**Bold text** here.More text after."

    def test_preserves_newlines_in_input(self):
        """Newlines are preserved (needed for markdown formatting)."""
        text = "Line one\nLine two\nLine three"
        result = strip_internal_tags(text)
        # Newlines preserved for markdown tables, code blocks, etc.
        assert result == "Line one\nLine two\nLine three"

    def test_removes_synthesis_instructions(self):
        """Remove synthesis instruction text."""
        text = (
            "Data here.Synthesize the search data into a clear answer. "
            "Do NOT reproduce raw results, source listings, or URLs.More text"
        )
        result = strip_internal_tags(text)
        assert "Synthesize" not in result
        assert "More text" in result

    def test_preserves_streaming_chunk_whitespace(self):
        """Streaming chunks with leading spaces should preserve them."""
        # This is the key fix for IG-053
        text = " the"  # Chunk with leading space
        result = strip_internal_tags(text)
        assert result == " the"  # Leading space preserved for proper concatenation
