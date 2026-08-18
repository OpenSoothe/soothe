"""Tests for typed soothe.stream.tool_call.update wire events."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from soothe_sdk.ux.stream_tool_wire import (
    STREAM_TOOL_CALL_UPDATE,
    extract_tool_call_updates_from_wire_message,
    tool_call_update_event,
)
from soothe_sdk.wire.codec import prepare_stream_message_for_wire


def test_tool_call_update_event_shape() -> None:
    ev = tool_call_update_event(
        tool_call_id="WAA_01:s:task:0",
        name="task",
        args={"subagent_type": "deep_research", "description": "scan repo"},
    )
    assert ev["type"] == STREAM_TOOL_CALL_UPDATE
    assert ev["tool_call_id"] == "WAA_01:s:task:0"
    assert ev["name"] == "task"
    assert ev["args"]["subagent_type"] == "deep_research"


def test_extract_from_flat_wire_ai_message() -> None:
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_file",
                "id": "ABC_01:s:read_file:0",
                "args": {"path": "/src/main.py"},
            }
        ],
    )
    wire = prepare_stream_message_for_wire(msg)
    updates = extract_tool_call_updates_from_wire_message(wire)
    assert len(updates) == 1
    assert updates[0]["type"] == STREAM_TOOL_CALL_UPDATE
    assert updates[0]["args"]["path"] == "/src/main.py"


def test_extract_skips_incomplete_args() -> None:
    wire = {
        "type": "ai",
        "content": "",
        "tool_call_chunks": [
            {"name": "grep", "id": "x:0", "args": ""},
        ],
    }
    assert extract_tool_call_updates_from_wire_message(wire) == []


def test_extract_unified_main_tool_without_args() -> None:
    """Daemon batch must surface main-graph tools before kwargs finish streaming."""
    wire = {
        "type": "ai",
        "content": "",
        "tool_calls": [
            {"name": "read_file", "id": "ABC_01:s:read_file:0", "args": {}},
        ],
    }
    updates = extract_tool_call_updates_from_wire_message(wire)
    assert len(updates) == 1
    assert updates[0]["tool_call_id"] == "ABC_01:s:read_file:0"
    assert updates[0]["name"] == "read_file"


def test_extract_unified_main_tool_chunk_without_args() -> None:
    """Streaming chunks with unified ids must batch before kwargs arrive."""
    wire = {
        "type": "ai",
        "content": "",
        "tool_call_chunks": [
            {"name": "grep", "id": "ABC_01:s:grep:0", "args": ""},
        ],
    }
    updates = extract_tool_call_updates_from_wire_message(wire)
    assert len(updates) == 1
    assert updates[0]["tool_call_id"] == "ABC_01:s:grep:0"
    assert updates[0]["name"] == "grep"


def test_extract_dedupes_tool_calls_and_chunks() -> None:
    wire = {
        "type": "ai",
        "content": "",
        "tool_calls": [
            {
                "name": "task",
                "id": "WAA_01:s:task:0",
                "args": {"subagent_type": "deep_research"},
            }
        ],
        "tool_call_chunks": [
            {
                "name": "task",
                "id": "WAA_01:s:task:0",
                "args": {"subagent_type": "deep_research"},
            }
        ],
    }
    updates = extract_tool_call_updates_from_wire_message(wire)
    assert len(updates) == 1
