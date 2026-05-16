"""Tests for stream tool-call diagnostic summaries."""

from __future__ import annotations

from langchain_core.messages import AIMessageChunk, ToolMessage

from soothe_sdk.ux.stream_tool_diag import (
    is_tool_visible_messages_summary,
    summarize_messages_stream_payload,
)


def test_summarize_tool_message_object() -> None:
    msg = ToolMessage(content="x", tool_call_id="abc", name="grep")
    assert "ToolMessage" in summarize_messages_stream_payload((msg, {}))


def test_summarize_ai_tool_chunk() -> None:
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": "ls", "id": "functions.ls:0", "args": ""}],
    )
    s = summarize_messages_stream_payload((chunk, {}))
    assert "AI-tool" in s
    assert is_tool_visible_messages_summary(s)
