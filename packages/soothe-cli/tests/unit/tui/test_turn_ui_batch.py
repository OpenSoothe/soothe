"""Turn-level TUI coalescing and incremental overlay helpers."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessageChunk

from soothe_cli.events.tools.message_processing import tool_ids_touched_by_stream_message
from soothe_cli.events.tools.tool_call_resolution import build_streaming_args_overlay
from soothe_cli.tui.textual_adapter import TurnToolUiCoalescer


def test_tool_ids_touched_by_stream_message_collects_chunk_ids() -> None:
    msg = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"name": "grep", "id": "call-1", "args": '{"pattern": "x"}'},
            {"name": "read_file", "id": "call-2", "args": ""},
        ],
    )
    assert tool_ids_touched_by_stream_message(msg) == {"call-1", "call-2"}


def test_build_streaming_args_overlay_incremental_only_scans_touched() -> None:
    pending = {
        "call-1": {
            "name": "grep",
            "args_str": '{"pattern": "a"}',
            "is_complete_json": True,
        },
        "call-2": {
            "name": "read_file",
            "args_str": '{"path": "/tmp/x"}',
            "is_complete_json": True,
        },
    }
    msg = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": "grep", "id": "call-1", "args": ""}],
    )
    overlay = build_streaming_args_overlay(msg, pending, only_ids={"call-1"})
    assert set(overlay.keys()) == {"call-1"}
    assert overlay["call-1"]["pattern"] == "a"


def test_turn_tool_ui_coalescer_wire_dedup() -> None:
    coalesce = TurnToolUiCoalescer()
    args = {"path": "/src/main.py"}
    assert coalesce.note_wire_apply("tc-1", args) is False
    assert coalesce.note_wire_apply("tc-1", args) is True
    assert coalesce.wire_applied("tc-1")
    coalesce.execute_wave_active = True
    assert coalesce.should_skip_messages_arg_refresh("tc-1")


@pytest.mark.asyncio
async def test_turn_tool_ui_coalescer_after_chunk_yields() -> None:
    coalesce = TurnToolUiCoalescer()
    await coalesce.after_chunk(force_flush=True)
