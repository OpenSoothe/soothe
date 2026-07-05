"""Tests for RFC-614 loop assistant output phase registry."""

from __future__ import annotations

from langchain_core.messages import messages_from_dict

from soothe_sdk.client.wire import envelope_langchain_message_dict
from soothe_sdk.ux.loop_stream import (
    GOAL_COMPLETION_STREAM_TERMINAL_FIELD,
    LOOP_ASSISTANT_OUTPUT_PHASES,
    assistant_output_phase,
    build_goal_completion_stream_terminal_message,
    is_goal_completion_stream_terminal,
)


def test_chitchat_phase_in_allowlist() -> None:
    assert "chitchat" in LOOP_ASSISTANT_OUTPUT_PHASES
    assert "goal_completion" in LOOP_ASSISTANT_OUTPUT_PHASES


def test_legacy_trivial_quiz_phases_removed() -> None:
    assert "trivial" not in LOOP_ASSISTANT_OUTPUT_PHASES
    assert "quiz" not in LOOP_ASSISTANT_OUTPUT_PHASES


def test_direct_model_phase_in_allowlist() -> None:
    assert "direct_model" in LOOP_ASSISTANT_OUTPUT_PHASES


def test_assistant_output_phase_recognizes_direct_model_after_wire_roundtrip() -> None:
    """Daemon direct model replies serialize ``phase``; clients must classify them."""
    flat = {
        "type": "ai",
        "content": "summary text",
        "phase": "direct_model",
        "tool_calls": [],
        "invalid_tool_calls": [],
    }
    wrapped = envelope_langchain_message_dict(flat)
    restored = messages_from_dict([wrapped])[0]
    assert assistant_output_phase(restored) == "direct_model"


def test_assistant_output_phase_on_plain_dict() -> None:
    msg = {"type": "ai", "content": "x", "phase": "direct_model"}
    assert assistant_output_phase(msg) == "direct_model"


def test_is_goal_completion_stream_terminal_prefers_stream_terminal_flag() -> None:
    wire = build_goal_completion_stream_terminal_message()
    assert is_goal_completion_stream_terminal(wire)


def test_is_goal_completion_stream_terminal_chunk_position_last_without_stream_terminal() -> None:
    """Older wire frames may omit ``stream_terminal`` on the final content block."""
    msg = {
        "type": "AIMessageChunk",
        "content": "done",
        "phase": "goal_completion",
        "chunk_position": "last",
    }
    assert is_goal_completion_stream_terminal(msg)


def test_is_goal_completion_stream_terminal_rejects_non_goal_completion() -> None:
    msg = {"type": "AIMessageChunk", "content": "", GOAL_COMPLETION_STREAM_TERMINAL_FIELD: True}
    assert not is_goal_completion_stream_terminal(msg)
