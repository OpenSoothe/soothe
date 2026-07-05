"""Tests for RFC-614 loop assistant output phase registry."""

from __future__ import annotations

from langchain_core.messages import messages_from_dict

from soothe_sdk.client.wire import envelope_langchain_message_dict
from soothe_sdk.ux.loop_stream import LOOP_ASSISTANT_OUTPUT_PHASES, assistant_output_phase


def test_trivial_phase_in_allowlist() -> None:
    assert "chitchat" in LOOP_ASSISTANT_OUTPUT_PHASES
    assert "trivial" in LOOP_ASSISTANT_OUTPUT_PHASES


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
