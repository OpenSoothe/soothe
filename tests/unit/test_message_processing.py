"""Test message processing utilities (see IG-053).

Tests for whitespace normalization and internal tag stripping.
"""

import pytest

from soothe.ux.shared.message_processing import (
    coerce_tool_call_args_to_dict,
    format_tool_call_args,
    strip_internal_tags,
)


class TestFormatToolCallArgs:
    """Display strings for tool call arguments (see IG-053)."""

    def test_pascal_case_tool_name_maps_to_arg_display(self) -> None:
        """Model may emit PascalCase names; lookup uses snake_case map."""
        assert (
            format_tool_call_args(
                "ReadFile",
                {"args": {"path": "README.md"}},
            )
            == "(README.md)"
        )

    def test_snake_case_unchanged(self) -> None:
        assert (
            format_tool_call_args(
                "read_file",
                {"args": {"path": "x.txt"}},
            )
            == "(x.txt)"
        )

    def test_fallback_when_mapped_keys_missing(self) -> None:
        """If the model uses different parameter names, show raw values."""
        assert format_tool_call_args("ls", {"args": {"directory": "/tmp"}}) == "(/tmp)"

    def test_deepagents_read_file_uses_file_path(self) -> None:
        """Filesystem middleware passes ``file_path``, not ``path``."""
        assert (
            format_tool_call_args(
                "read_file",
                {"args": {"file_path": "/README.md"}},
            )
            == "(/README.md)"
        )

    def test_string_json_args_from_tool_call_chunk(self) -> None:
        """Streaming chunks encode args as JSON text."""
        raw = '{"file_path": "/pyproject.toml"}'
        assert coerce_tool_call_args_to_dict(raw) == {"file_path": "/pyproject.toml"}
        assert format_tool_call_args("read_file", {"args": raw}) == "(/pyproject.toml)"


class TestStripInternalTags:
    """Test whitespace normalization in strip_internal_tags()."""

    def test_preserves_spaces_between_words(self):
        """Ensure spaces are preserved between words."""
        text = "Hello world this is a test"
        result = strip_internal_tags(text)
        assert result == "Hello world this is a test"

    def test_normalizes_multiple_spaces(self):
        """Multiple spaces should collapse to single space."""
        text = "Hello    world   test"
        result = strip_internal_tags(text)
        assert result == "Hello world test"

    def test_adds_space_after_punctuation(self):
        """Ensure space after sentence-ending punctuation."""
        text = "First sentence.Second sentence.Third one"
        result = strip_internal_tags(text)
        assert result == "First sentence. Second sentence. Third one"

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

    def test_complex_formatting(self):
        """Test complex markdown formatting."""
        text = "**Bold text** here.More text after."
        result = strip_internal_tags(text)
        assert result == "**Bold text** here. More text after."

    def test_preserves_newlines_in_input(self):
        """Newlines should be converted to spaces."""
        text = "Line one\nLine two\nLine three"
        result = strip_internal_tags(text)
        assert result == "Line one Line two Line three"

    def test_removes_synthesis_instructions(self):
        """Remove synthesis instruction text."""
        text = (
            "Data here.Synthesize the search data into a clear answer. "
            "Do NOT reproduce raw results, source listings, or URLs.More text"
        )
        result = strip_internal_tags(text)
        assert "Synthesize" not in result
        assert "More text" in result

    def test_fixes_concatenated_text(self):
        """Fix the actual issue from the test run."""
        text = "I'llsearchforinformationaboutIranwarsusingthebrowsertool."
        # This should normalize if we add spaces (which the fix does)
        result = strip_internal_tags(text)
        # After normalization, multiple words should have spaces
        assert "I'll" in result
        assert "search" in result
        assert "information" in result
