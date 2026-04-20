"""Tests for daemon WebSocket message normalization in the TUI."""

from langchain_core.messages import AIMessage, AIMessageChunk, messages_from_dict
from soothe_sdk.client.protocol import _serialize_for_json
from soothe_sdk.langchain_wire import envelope_langchain_message_dict

from soothe_cli.tui.daemon_session import TuiDaemonSession


def test_envelope_wraps_flat_ai_message_dict() -> None:
    """Flat model_dump-style dict must become messages_from_dict-compatible."""
    flat = _serialize_for_json(AIMessage(content="hello", id="m1"))
    assert isinstance(flat, dict)
    assert "data" not in flat
    wrapped = envelope_langchain_message_dict(flat)
    assert wrapped["type"] == "ai"
    assert "data" in wrapped
    restored = messages_from_dict([wrapped])
    assert isinstance(restored[0], AIMessage)
    assert restored[0].content == "hello"


def test_envelope_wraps_flat_chunk_dict() -> None:
    flat = _serialize_for_json(AIMessageChunk(content="partial"))
    wrapped = envelope_langchain_message_dict(flat)
    restored = messages_from_dict([wrapped])
    assert isinstance(restored[0], AIMessageChunk)
    assert restored[0].content == "partial"


def test_envelope_maps_aimessage_class_name_to_wire_tag() -> None:
    """Serializers that emit ``type: \"AIMessage\"`` must map to ``ai`` for LC."""
    flat = {
        "type": "AIMessage",
        "content": "",
        "tool_calls": [
            {
                "name": "read_file",
                "args": {"file_path": "a.txt"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    }
    wrapped = envelope_langchain_message_dict(flat)
    assert wrapped["type"] == "ai"
    restored = messages_from_dict([wrapped])
    assert isinstance(restored[0], AIMessage)
    assert restored[0].tool_calls


def test_envelope_idempotent_when_data_present() -> None:
    """Already-enveloped LC dicts are unchanged."""
    m = AIMessage(content="x")
    from langchain_core.messages import message_to_dict

    good = message_to_dict(m)
    assert envelope_langchain_message_dict(good) is good


def test_normalize_stream_data_restores_ai_message() -> None:
    """``_normalize_stream_data`` must yield AIMessage instances for flat wire dicts."""
    session = object.__new__(TuiDaemonSession)
    flat = _serialize_for_json(AIMessage(content="wire"))
    out = session._normalize_stream_data(
        "messages",
        (flat, {"langgraph_step": 1}),
    )
    assert isinstance(out, tuple) and len(out) == 2
    msg, meta = out
    assert isinstance(msg, AIMessage)
    assert msg.content == "wire"
    assert meta == {"langgraph_step": 1}
