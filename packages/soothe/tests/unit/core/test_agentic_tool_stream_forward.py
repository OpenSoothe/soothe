"""Tests for agentic runner forwarding of tool message stream chunks."""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from soothe.core.runner._runner_agentic import _is_tool_stream_chunk


def test_tool_stream_chunk_detects_tool_message() -> None:
    msg = ToolMessage(content="ok", tool_call_id="call-1", name="ls")
    chunk: tuple[tuple[str, ...], str, tuple[object, dict]] = (
        (),
        "messages",
        (msg, {}),
    )
    assert _is_tool_stream_chunk(chunk) is True


def test_tool_stream_chunk_detects_serialized_dict() -> None:
    chunk = (
        (),
        "messages",
        ({"type": "tool", "content": "x", "tool_call_id": "c1", "name": "glob"}, {}),
    )
    assert _is_tool_stream_chunk(chunk) is True


def test_tool_stream_chunk_rejects_ai_message() -> None:
    chunk = (
        (),
        "messages",
        (AIMessage(content="hello"), {}),
    )
    assert _is_tool_stream_chunk(chunk) is False


def test_tool_stream_chunk_rejects_custom_mode() -> None:
    msg = ToolMessage(content="ok", tool_call_id="call-1", name="ls")
    chunk = ((), "custom", (msg, {}))
    assert _is_tool_stream_chunk(chunk) is False
