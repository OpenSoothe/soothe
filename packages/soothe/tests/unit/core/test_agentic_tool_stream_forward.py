"""Tests for agentic runner forwarding of tool message stream chunks."""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from soothe.core.runner._runner_agentic import (
    _forward_messages_chunk_for_tool_ui,
    _is_ai_tool_invocation_messages_chunk,
    _is_tool_stream_chunk,
)


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


def test_ai_tool_invocation_chunk_with_tool_calls() -> None:
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_file",
                "args": {"file_path": "README.md"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    chunk = ((), "messages", (msg, {}))
    assert _is_ai_tool_invocation_messages_chunk(chunk) is True
    assert _forward_messages_chunk_for_tool_ui(chunk) is True


def test_ai_tool_invocation_chunk_rejects_plain_text_ai() -> None:
    chunk = ((), "messages", (AIMessage(content="hello"), {}))
    assert _is_ai_tool_invocation_messages_chunk(chunk) is False
    assert _forward_messages_chunk_for_tool_ui(chunk) is False


def test_forward_combines_tool_message_and_ai_tool_invocation() -> None:
    tool_chunk = ((), "messages", (ToolMessage(content="ok", tool_call_id="c1", name="ls"), {}))
    ai_plain = ((), "messages", (AIMessage(content="hi"), {}))
    assert _forward_messages_chunk_for_tool_ui(tool_chunk) is True
    assert _forward_messages_chunk_for_tool_ui(ai_plain) is False


def test_forward_remains_tool_only_for_plain_ai_messages() -> None:
    tool_chunk = ((), "messages", (ToolMessage(content="ok", tool_call_id="c1", name="ls"), {}))
    ai_plain = ((), "messages", (AIMessage(content="hi"), {}))
    assert _forward_messages_chunk_for_tool_ui(tool_chunk) is True
    assert _forward_messages_chunk_for_tool_ui(ai_plain) is False
