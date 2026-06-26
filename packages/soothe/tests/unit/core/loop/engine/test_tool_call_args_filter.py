"""Tests for redundant stream tool update filtering."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from soothe.foundation.loop.engine.tool_call_args import (
    filter_redundant_stream_tool_updates,
    wire_updates_from_ai_message,
)


def test_filter_drops_complete_args_updates() -> None:
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_file",
                "args": {"path": "/x"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    updates = wire_updates_from_ai_message(msg)
    assert len(updates) == 1
    assert filter_redundant_stream_tool_updates(updates) == []


def test_filter_keeps_incomplete_args_updates() -> None:
    updates = [
        {
            "type": "soothe.stream.tool_call.update",
            "tool_call_id": "call-1",
            "name": "read_file",
            "args": {},
        }
    ]
    assert filter_redundant_stream_tool_updates(updates) == updates


def test_wire_updates_emits_unified_main_tool_without_args() -> None:
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_file",
                "args": {},
                "id": "BCO_01:s:read_file:0",
                "type": "tool_call",
            }
        ],
    )
    updates = wire_updates_from_ai_message(msg)
    assert len(updates) == 1
    assert updates[0]["tool_call_id"] == "BCO_01:s:read_file:0"
    assert updates[0]["name"] == "read_file"
