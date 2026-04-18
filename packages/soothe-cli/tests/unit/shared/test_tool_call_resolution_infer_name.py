"""Tests for inferring real tool names from ``functions.<name>:idx`` ids."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from soothe_cli.shared.tool_call_resolution import (
    infer_tool_name_from_call_id,
    materialize_ai_blocks_with_resolved_tools,
)


def test_infer_tool_name_from_functions_prefix() -> None:
    assert infer_tool_name_from_call_id("functions.ls:0") == "ls"
    assert infer_tool_name_from_call_id("functions.read_file:12") == "read_file"
    assert infer_tool_name_from_call_id("") is None
    assert infer_tool_name_from_call_id("call-abc") is None


def test_materialize_replaces_literal_tool_name_using_id() -> None:
    """When the provider sets name to ``tool``, merge uses the id-encoded tool."""
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "tool",
                "id": "functions.ls:0",
                "args": {"path": "."},
                "type": "tool_call",
            },
        ],
    )
    blocks = [{"type": "tool_call", "name": "tool", "id": "functions.ls:0", "args": {}}]
    merged = materialize_ai_blocks_with_resolved_tools(blocks, msg, streaming_overlay=None)
    assert merged[0]["name"] == "ls"
    assert merged[0]["args"].get("path") == "."
