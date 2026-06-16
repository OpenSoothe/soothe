"""Test message processing utilities (see IG-053)."""

from __future__ import annotations

from typing import Any

from soothe_cli.runtime.parse.message_processing import (
    _normalize_tool_name_for_arg_map,
    accumulate_tool_call_chunks,
    extract_tool_args_dict,
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

    def test_value_wrapper_key_stripped(self) -> None:
        """Sentinel ``{"value": X}`` from non-dict args must not appear as fake arg.

        When raw args is a boolean/int (e.g., ``True``), textual_adapter wraps it as
        ``{"value": True}``. This sentinel must be stripped to avoid displaying
        ``ReadFile(True)`` instead of proper ``ReadFile``.
        """
        assert extract_tool_args_dict({"value": True}) == {}
        assert extract_tool_args_dict({"value": False}) == {}
        assert extract_tool_args_dict({"value": 123}) == {}
        assert extract_tool_args_dict({"value": "str"}) == {}

    def test_subgraph_tool_placeholder_stripped(self) -> None:
        """Wire placeholder ``{"_subgraph_tool": true}`` must not display as ``ReadFile(True)``."""
        assert extract_tool_args_dict({"_subgraph_tool": True}) == {}
        assert extract_tool_args_dict({"_subgraph_tool": False}) == {}


class TestNormalizeToolNameForArgMap:
    """Snake_case normalization for step-card tool stats."""

    def test_pascal_case_to_snake(self) -> None:
        assert _normalize_tool_name_for_arg_map("ReadFile") == "read_file"

    def test_snake_case_unchanged(self) -> None:
        assert _normalize_tool_name_for_arg_map("read_file") == "read_file"
