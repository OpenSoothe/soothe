"""Unit tests for tool-call kwargs collection during Act streaming."""

from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk
from soothe.foundation.sloop.engine.tool_call_args import (
    ToolCallArgsCollector,
    format_args_for_log,
)


def test_format_args_for_log_truncates_long_payload() -> None:
    args = {"command": "x" * 600}
    preview = format_args_for_log(args, max_chars=80)
    assert preview.endswith("...")
    assert len(preview) <= 83


def test_record_ai_pair_backfills_from_chunks() -> None:
    msg = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "grep", "args": {}}],
        tool_call_chunks=[
            {
                "id": "call_1",
                "name": "grep",
                "args": '{"pattern": "foo", "path": "."}',
            }
        ],
    )
    collector = ToolCallArgsCollector()
    collector.record_ai_pair(msg, msg)
    assert collector.lookup("call_1") == {"pattern": "foo", "path": "."}


def test_record_ai_pair_maps_index_only_chunk_to_unified_id() -> None:
    """Index-only streaming chunks must be keyed by unified id for ToolMessage lookup."""
    msg = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "index": 7,
                "name": "edit_file",
                "args": '{"file_path": "README.md", "old_string": "a", "new_string": "b"}',
            },
        ],
    )
    collector = ToolCallArgsCollector()
    collector.record_ai_pair(msg, msg, step_id="YJH-01")
    assert collector.lookup("YJH_01:s:edit_file:7") == {
        "file_path": "README.md",
        "old_string": "a",
        "new_string": "b",
    }
