"""Tests for stream tool-call state ingestion (wire dict + LangChain)."""

from __future__ import annotations

from langchain_core.messages import AIMessageChunk

from soothe_cli.events.tools.message_processing import (
    ingest_tool_call_stream_state,
    try_parse_pending_tool_call_args,
)
from soothe_cli.events.tools.tool_call_resolution import build_streaming_args_overlay


def test_ingest_wire_dict_seeds_complete_tool_calls() -> None:
    pending: dict = {}
    wire = {
        "type": "ai",
        "tool_calls": [
            {
                "name": "task",
                "id": "WAA_01:s:task:0",
                "args": {
                    "description": "Explore the repo",
                    "subagent_type": "explore",
                },
            }
        ],
    }
    ingest_tool_call_stream_state(pending, wire, is_main=True)
    assert "WAA_01:s:task:0" in pending
    parsed = try_parse_pending_tool_call_args(pending["WAA_01:s:task:0"])
    assert parsed is not None
    assert parsed.get("subagent_type") == "explore"
    overlay = build_streaming_args_overlay(AIMessageChunk(content=""), pending)
    assert overlay["WAA_01:s:task:0"]["description"] == "Explore the repo"
