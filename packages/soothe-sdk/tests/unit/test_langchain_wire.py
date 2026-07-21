"""Tests for LangChain JSON wire normalization."""

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    message_to_dict,
    messages_from_dict,
)

from soothe_sdk.wire.codec import (
    deserialize_langchain_message_from_wire,
    envelope_langchain_message_dict,
    messages_from_wire_dicts,
    prepare_stream_data_for_wire,
    prepare_stream_message_for_wire,
)
from soothe_sdk.wire.protocol import _serialize_for_json


def test_messages_from_wire_dicts_flat_human() -> None:
    """Flat HumanMessage dicts (no ``data`` envelope) deserialize without KeyError."""
    flat = _serialize_for_json(HumanMessage(content="hi"))
    assert isinstance(flat, dict)
    assert "data" not in flat
    out = messages_from_wire_dicts([flat])
    assert len(out) == 1
    assert isinstance(out[0], HumanMessage)
    assert out[0].content == "hi"


def test_messages_from_wire_dicts_mixed_with_message_to_dict() -> None:
    """Already-enveloped dicts (``message_to_dict``) still work."""
    m = AIMessage(content="x")
    enveloped = message_to_dict(m)
    flat = _serialize_for_json(HumanMessage(content="y"))
    out = messages_from_wire_dicts([enveloped, flat])
    assert isinstance(out[0], AIMessage)
    assert isinstance(out[1], HumanMessage)


def test_messages_from_wire_dicts_coerces_dict_tool_call_chunk_args() -> None:
    """Dict chunk args (executor enrich) deserialize with coerced chunk arg strings."""
    flat = {
        "type": "ai",
        "content": "",
        "tool_calls": [
            {
                "name": "task",
                "id": "WAA_01:s:task:0",
                "args": {
                    "description": "Explore repository structure",
                    "subagent_type": "deep_research",
                },
            }
        ],
        "tool_call_chunks": [
            {
                "name": "task",
                "id": "WAA_01:s:task:0",
                "args": {
                    "description": "Explore repository structure",
                    "subagent_type": "deep_research",
                },
            }
        ],
    }
    out = messages_from_wire_dicts([flat])
    assert len(out) == 1
    assert isinstance(out[0], AIMessage)
    assert out[0].tool_calls[0]["args"]["description"] == "Explore repository structure"
    assert isinstance(out[0].tool_call_chunks[0]["args"], str)
    assert "Explore" in out[0].tool_call_chunks[0]["args"]


def test_wire_backfills_empty_tool_calls_from_chunks() -> None:
    from langchain_core.messages import AIMessage

    msg = AIMessage(
        content="",
        tool_calls=[{"name": "read_file", "id": "abc", "args": {}}],
        tool_call_chunks=[
            {"name": "read_file", "id": "abc", "args": '{"path":"/x.py","limit":99}'}
        ],
    )
    flat = prepare_stream_message_for_wire(msg)
    assert flat["tool_calls"][0]["args"]["path"] == "/x.py"
    assert flat["tool_calls"][0]["args"]["limit"] == 99


def test_prepare_stream_message_preserves_tool_call_args() -> None:
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_file",
                "id": "ABC_01:s:read_file:0",
                "args": {"path": "/src/main.py"},
            }
        ],
    )
    flat = prepare_stream_message_for_wire(msg)
    assert isinstance(flat, dict)
    assert flat["type"] == "ai"
    assert flat["tool_calls"][0]["args"]["path"] == "/src/main.py"
    restored = deserialize_langchain_message_from_wire(flat)
    assert isinstance(restored, AIMessage)
    assert restored.tool_calls[0]["args"]["path"] == "/src/main.py"


def test_prepare_stream_data_for_wire_pair() -> None:
    chunk = AIMessageChunk(
        content="",
        tool_calls=[{"name": "grep", "id": "x:0", "args": {"pattern": "foo"}}],
    )
    msg, meta = prepare_stream_data_for_wire((chunk, {"lc_source": "agent"}))
    assert isinstance(msg, dict)
    # IG-440: AIMessageChunk identity MUST be preserved on the wire so the TUI
    # streaming branch (``isinstance(msg, AIMessageChunk)``) fires for synthesis
    # chunks. Collapsing to ``ai`` would restore as plain AIMessage on the client.
    assert msg["type"] == "AIMessageChunk"
    assert msg["tool_calls"][0]["args"]["pattern"] == "foo"
    assert meta == {"lc_source": "agent"}


def test_ai_message_chunk_roundtrip_preserves_chunk_identity() -> None:
    """IG-440 regression: AIMessageChunk on wire → restored as AIMessageChunk (not AIMessage).

    The pre-IG-440 mapping collapsed ``AIMessageChunk`` → wire tag ``ai`` for
    ``messages_from_dict`` compatibility. That mapping caused synthesis stream
    chunks to deserialize as plain ``AIMessage`` on the client, breaking the TUI
    ``isinstance(msg, AIMessageChunk)`` check and silently dropping every chunk
    after the first one.
    """
    chunk = AIMessageChunk(content="hello")
    flat = prepare_stream_message_for_wire(chunk)
    assert flat["type"] == "AIMessageChunk"
    restored = deserialize_langchain_message_from_wire(flat)
    assert isinstance(restored, AIMessageChunk)
    assert not isinstance(restored, AIMessage) or isinstance(restored, AIMessageChunk)
    assert restored.content == "hello"


def test_ai_message_chunk_roundtrip_preserves_extra_phase_field() -> None:
    """IG-440 regression: extra fields like ``phase`` survive wire round-trip.

    The synthesis pipeline tags chunks with ``phase="goal_completion"``. The TUI
    needs the chunk identity AND the phase attribute to route the goal-completion
    streaming branch. Both must survive serialization → wire → deserialization.
    """
    chunk = AIMessageChunk(content="Synthesis fragment.", phase="goal_completion")
    flat = prepare_stream_message_for_wire(chunk)
    assert flat["type"] == "AIMessageChunk"
    assert flat.get("phase") == "goal_completion"

    restored = deserialize_langchain_message_from_wire(flat)
    assert isinstance(restored, AIMessageChunk), (
        f"expected AIMessageChunk, got {type(restored).__name__}"
    )
    assert getattr(restored, "phase", None) == "goal_completion"
    assert restored.content == "Synthesis fragment."


def test_envelope_idempotent_message_to_dict() -> None:
    m = AIMessage(content="x")
    good = message_to_dict(m)
    assert envelope_langchain_message_dict(good) is good
    restored = messages_from_dict([good])
    assert isinstance(restored[0], AIMessage)
