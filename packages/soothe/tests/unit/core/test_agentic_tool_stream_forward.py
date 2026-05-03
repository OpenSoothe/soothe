"""Tests for agentic runner forwarding of tool message stream chunks."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from soothe.core.agent_loop.utils.messages import (
    LoopAIMessageChunk,
    loop_message_assistant_output_phase,
)
from soothe.core.runner._runner_agentic import (
    _forward_messages_chunk_for_tool_ui,
    _is_ai_messages_stream_chunk,
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


def test_plain_text_ai_forwarded_but_not_tool_invocation_chunk() -> None:
    chunk = ((), "messages", (AIMessage(content="hello"), {}))
    assert _is_ai_tool_invocation_messages_chunk(chunk) is False
    assert _is_ai_messages_stream_chunk(chunk) is True
    assert _forward_messages_chunk_for_tool_ui(chunk) is True


def test_forward_combines_tool_message_and_plain_ai() -> None:
    tool_chunk = ((), "messages", (ToolMessage(content="ok", tool_call_id="c1", name="ls"), {}))
    ai_plain = ((), "messages", (AIMessage(content="hi"), {}))
    assert _forward_messages_chunk_for_tool_ui(tool_chunk) is True
    assert _forward_messages_chunk_for_tool_ui(ai_plain) is True


def test_loop_assistant_chunk_is_forwarded() -> None:
    msg = LoopAIMessageChunk(
        content="syn",
        phase="goal_completion",
        thread_id="t-1",
        iteration=1,
    )
    chunk: tuple[tuple[str, ...], str, tuple[object, dict]] = ((), "messages", (msg, {}))
    assert loop_message_assistant_output_phase(msg) == "goal_completion"
    assert _forward_messages_chunk_for_tool_ui(chunk) is True


def test_human_message_not_forwarded() -> None:
    chunk = ((), "messages", (HumanMessage(content="hi"), {}))
    assert _forward_messages_chunk_for_tool_ui(chunk) is False


def test_wire_dict_human_not_forwarded() -> None:
    chunk = ((), "messages", ({"type": "human", "content": "x"}, {}))
    assert _forward_messages_chunk_for_tool_ui(chunk) is False
