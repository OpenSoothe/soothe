"""Tests for agentic runner forwarding of tool message stream chunks."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

from soothe.core.loop.utils.messages import (
    LoopAIMessageChunk,
    loop_message_assistant_output_phase,
)
from soothe.core.runner._runner_agentic import (
    _forward_messages_chunk,
    _is_ai_messages_stream_chunk,
    _is_ai_tool_invocation_messages_chunk,
    _is_subgraph_tool_call_update_chunk,
    _is_tool_call_update_chunk,
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
    assert _forward_messages_chunk(chunk) is True


def test_plain_text_ai_forwarded_but_not_tool_invocation_chunk() -> None:
    chunk = ((), "messages", (AIMessage(content="hello"), {}))
    assert _is_ai_tool_invocation_messages_chunk(chunk) is False
    assert _is_ai_messages_stream_chunk(chunk) is True
    assert _forward_messages_chunk(chunk) is True


def test_forward_combines_tool_message_and_plain_ai() -> None:
    tool_chunk = ((), "messages", (ToolMessage(content="ok", tool_call_id="c1", name="ls"), {}))
    ai_plain = ((), "messages", (AIMessage(content="hi"), {}))
    assert _forward_messages_chunk(tool_chunk) is True
    assert _forward_messages_chunk(ai_plain) is True


def test_loop_assistant_chunk_is_forwarded() -> None:
    msg = LoopAIMessageChunk(
        content="syn",
        phase="goal_completion",
        thread_id="t-1",
        iteration=1,
    )
    chunk: tuple[tuple[str, ...], str, tuple[object, dict]] = ((), "messages", (msg, {}))
    assert loop_message_assistant_output_phase(msg) == "goal_completion"
    assert _forward_messages_chunk(chunk) is True


def test_human_message_not_forwarded() -> None:
    chunk = ((), "messages", (HumanMessage(content="hi"), {}))
    assert _forward_messages_chunk(chunk) is False


def test_wire_dict_human_not_forwarded() -> None:
    chunk = ((), "messages", ({"type": "human", "content": "x"}, {}))
    assert _forward_messages_chunk(chunk) is False


def test_subgraph_tool_call_update_forwarded() -> None:
    """Namespaced custom tool_call_update events should be forwarded."""
    chunk = (
        ("tools:abc123",),
        "custom",
        {
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "DKG_01:t0:glob:0",
            "name": "glob",
            "args": {"pattern": "*.py"},
        },
    )
    assert _is_subgraph_tool_call_update_chunk(chunk) is True
    assert _forward_messages_chunk(chunk) is True


def test_main_graph_tool_call_update_forwarded() -> None:
    """Main-graph tool_call_update custom events are forwarded to clients."""
    chunk = (
        (),
        "custom",
        {
            "type": STREAM_TOOL_CALL_UPDATE,
            "tool_call_id": "DKG_01:s:edit_file:0",
            "name": "edit_file",
            "args": {
                "file_path": "/tmp/a.py",
                "old_string": "foo",
                "new_string": "bar",
            },
        },
    )
    assert _is_subgraph_tool_call_update_chunk(chunk) is False
    assert _is_tool_call_update_chunk(chunk) is True
    assert _forward_messages_chunk(chunk) is True


def test_empty_ai_chunk_not_forwarded() -> None:
    chunk = ((), "messages", (AIMessage(content=""), {}))
    assert _is_ai_messages_stream_chunk(chunk) is False
    assert _forward_messages_chunk(chunk) is False


def test_empty_ai_chunk_with_tool_calls_still_forwarded() -> None:
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "edit_file",
                "args": {"file_path": "a.py"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    chunk = ((), "messages", (msg, {}))
    assert _is_ai_messages_stream_chunk(chunk) is True
    assert _forward_messages_chunk(chunk) is True


def test_custom_event_non_tool_update_not_forwarded() -> None:
    """Other custom events (not tool_call_update) should not be forwarded."""
    chunk = (
        ("tools:abc123",),
        "custom",
        {"type": "soothe.subagent.explore.started"},
    )
    assert _is_subgraph_tool_call_update_chunk(chunk) is False
    assert _forward_messages_chunk(chunk) is False
