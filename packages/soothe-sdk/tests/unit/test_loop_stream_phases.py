"""Tests for RFC-614 loop assistant output phase registry."""

from __future__ import annotations

from langchain_core.messages import messages_from_dict

from soothe_sdk.ux.loop_stream import (
    GOAL_COMPLETION_STREAM_TERMINAL_FIELD,
    LOOP_ASSISTANT_OUTPUT_PHASES,
    assistant_output_phase,
    is_goal_completion_stream_terminal,
    is_stream_terminal,
    is_stream_terminal_wire_dict,
)
from soothe_sdk.wire.codec import envelope_langchain_message_dict


def test_chitchat_phase_in_allowlist() -> None:
    assert "chitchat" in LOOP_ASSISTANT_OUTPUT_PHASES
    assert "goal_completion" in LOOP_ASSISTANT_OUTPUT_PHASES


def test_legacy_trivial_quiz_phases_removed() -> None:
    assert "trivial" not in LOOP_ASSISTANT_OUTPUT_PHASES
    assert "quiz" not in LOOP_ASSISTANT_OUTPUT_PHASES


def test_legacy_direct_model_phase_removed() -> None:
    assert "direct_model" not in LOOP_ASSISTANT_OUTPUT_PHASES


def test_assistant_output_phase_recognizes_text_completion_after_wire_roundtrip() -> None:
    """Daemon intent-hint replies serialize ``phase``; clients must classify them."""
    flat = {
        "type": "ai",
        "content": "summary text",
        "phase": "text_completion",
        "tool_calls": [],
        "invalid_tool_calls": [],
    }
    wrapped = envelope_langchain_message_dict(flat)
    restored = messages_from_dict([wrapped])[0]
    assert assistant_output_phase(restored) == "text_completion"


def test_assistant_output_phase_on_plain_dict() -> None:
    msg = {"type": "ai", "content": "x", "phase": "text_completion"}
    assert assistant_output_phase(msg) == "text_completion"


def test_is_stream_terminal_wire_dict_requires_stream_terminal_flag() -> None:
    assert is_stream_terminal_wire_dict({"stream_terminal": True})
    assert not is_stream_terminal_wire_dict({"chunk_position": "last"})
    assert not is_stream_terminal_wire_dict({"content": "x"})


def test_is_goal_completion_stream_terminal_requires_stream_terminal_flag() -> None:
    msg = {
        "type": "AIMessageChunk",
        "content": "done",
        "phase": "goal_completion",
        "stream_terminal": True,
    }
    assert is_goal_completion_stream_terminal(msg)
    assert not is_goal_completion_stream_terminal(
        {
            "type": "AIMessageChunk",
            "content": "done",
            "phase": "goal_completion",
            "chunk_position": "last",
        }
    )


def test_is_stream_terminal_on_langchain_message() -> None:
    from langchain_core.messages import AIMessageChunk

    assert is_stream_terminal(
        AIMessageChunk(content="", phase="goal_completion", stream_terminal=True)
    )
    assert not is_stream_terminal(
        AIMessageChunk(content="", phase="goal_completion", chunk_position="last")
    )


def test_is_goal_completion_stream_terminal_rejects_non_goal_completion() -> None:
    msg = {"type": "AIMessageChunk", "content": "", GOAL_COMPLETION_STREAM_TERMINAL_FIELD: True}
    assert not is_goal_completion_stream_terminal(msg)
