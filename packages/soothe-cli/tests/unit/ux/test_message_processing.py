"""Test message processing utilities (see IG-053).

Tests for whitespace normalization and internal tag stripping.
"""

from __future__ import annotations

from typing import Any

from soothe_cli.events.tools.message_processing import (
    _normalize_tool_name_for_arg_map,
    accumulate_tool_call_chunks,
    extract_tool_args_dict,
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

    def test_parallel_streams_accumulate_by_tool_call_id(self) -> None:
        """String fragments must append to the matching id (not the first pending)."""
        pending: dict[str, Any] = {}
        accumulate_tool_call_chunks(
            pending,
            [
                {"id": "call-a", "name": "read_file", "args": ""},
                {"id": "call-b", "name": "ls", "args": ""},
                {"id": "call-a", "args": '{"file_path": "'},
                {"id": "call-a", "args": '/tmp/x.md"}'},
                {"id": "call-b", "args": '{"directory": "/proj"}'},
            ],
        )
        assert pending["call-a"]["args_str"] == '{"file_path": "/tmp/x.md"}'
        assert pending["call-b"]["args_str"] == '{"directory": "/proj"}'

    def test_dict_then_string_replaces_not_concatenates(self) -> None:
        """Non-empty dict on first chunk + string fragments must REPLACE (not concatenate).

        This is the critical bug fix: if args_str already contains complete JSON from a
        dict, subsequent string fragments should restart accumulation, not concatenate.

        Provider pattern: sends initial dict with provisional args, then refines with strings.
        """
        pending: dict[str, Any] = {}

        # Chunk 1: non-empty dict (complete JSON)
        accumulate_tool_call_chunks(
            pending,
            [{"id": "call-1", "name": "read_file", "args": {"file_path": "/old.txt"}}],
        )
        assert pending["call-1"]["args_str"] == '{"file_path": "/old.txt"}'
        assert pending["call-1"]["is_complete_json"] is True

        # Chunk 2: string fragment (provider refined args)
        accumulate_tool_call_chunks(
            pending,
            [{"id": "call-1", "args": '{"path": "'}],
        )
        # Should REPLACE, not concatenate: '{"file_path": "/old.txt"}{"path": "' would be invalid
        assert pending["call-1"]["args_str"] == '{"path": "'
        assert pending["call-1"]["is_complete_json"] is False

        # Chunk 3: more string
        accumulate_tool_call_chunks(
            pending,
            [{"id": "call-1", "args": '/new.md"}'}],
        )
        assert pending["call-1"]["args_str"] == '{"path": "/new.md"}'
        assert pending["call-1"]["is_complete_json"] is False

        # Verify parse succeeds (would fail if concatenation bug present)
        parsed = try_parse_pending_tool_call_args(pending["call-1"])
        assert parsed == {"path": "/new.md"}

    def test_empty_dict_then_string_accumulates_normally(self) -> None:
        """Empty dict on first chunk + strings should work (not affected by fix)."""
        pending: dict[str, Any] = {}

        # Chunk 1: empty dict (falls to else → args_str = "")
        accumulate_tool_call_chunks(
            pending,
            [{"id": "call-2", "name": "ls", "args": {}}],
        )
        assert pending["call-2"]["args_str"] == ""
        assert pending["call-2"]["is_complete_json"] is False

        # Chunk 2: string fragment
        accumulate_tool_call_chunks(
            pending,
            [{"id": "call-2", "args": '{"directory": "'}],
        )
        assert pending["call-2"]["args_str"] == '{"directory": "'

        # Chunk 3: more string
        accumulate_tool_call_chunks(
            pending,
            [{"id": "call-2", "args": '/proj"}'}],
        )
        assert pending["call-2"]["args_str"] == '{"directory": "/proj"}'

        parsed = try_parse_pending_tool_call_args(pending["call-2"])
        assert parsed == {"directory": "/proj"}

    def test_dict_replacement_clears_string_accumulation(self) -> None:
        """String → dict replacement should work (existing behavior, preserved)."""
        pending: dict[str, Any] = {}

        # Chunk 1: string (partial)
        accumulate_tool_call_chunks(
            pending,
            [{"id": "call-3", "name": "read_file", "args": '{"old": "'}],
        )
        assert pending["call-3"]["args_str"] == '{"old": "'
        assert pending["call-3"]["is_complete_json"] is False

        # Chunk 2: complete dict (replaces)
        accumulate_tool_call_chunks(
            pending,
            [{"id": "call-3", "args": {"new": "/final"}}],
        )
        assert pending["call-3"]["args_str"] == '{"new": "/final"}'
        assert pending["call-3"]["is_complete_json"] is True

        parsed = try_parse_pending_tool_call_args(pending["call-3"])
        assert parsed == {"new": "/final"}


class TestExtractToolArgsDict:
    """``extract_tool_args_dict`` normalizes provider-specific shapes."""

    def test_openai_style_arguments_json_string(self) -> None:
        assert extract_tool_args_dict(
            {"name": "read_file", "id": "1", "arguments": '{"file_path": "/a.txt"}'}
        ) == {"file_path": "/a.txt"}

    def test_anthropic_style_input_dict(self) -> None:
        assert extract_tool_args_dict({"name": "ls", "input": {"path": "/b"}}) == {"path": "/b"}


class TestNormalizeToolNameForArgMap:
    """Snake_case normalization for step-card tool stats."""

    def test_pascal_case_to_snake(self) -> None:
        assert _normalize_tool_name_for_arg_map("ReadFile") == "read_file"

    def test_snake_case_unchanged(self) -> None:
        assert _normalize_tool_name_for_arg_map("read_file") == "read_file"


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
