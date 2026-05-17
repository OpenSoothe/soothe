"""Tests for LangChain JSON wire normalization."""

from langchain_core.messages import AIMessage, HumanMessage, message_to_dict, messages_from_dict

from soothe_sdk.client.protocol import _serialize_for_json
from soothe_sdk.langchain_wire import envelope_langchain_message_dict, messages_from_wire_dicts


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
    """Dict chunk args (executor enrich) must deserialize as AIMessageChunk."""
    from langchain_core.messages import AIMessageChunk

    flat = {
        "type": "AIMessageChunk",
        "content": "",
        "tool_calls": [
            {
                "name": "task",
                "id": "WAA-01:s:task:0",
                "args": {
                    "description": "Explore repository structure",
                    "subagent_type": "explore",
                },
            }
        ],
        "tool_call_chunks": [
            {
                "name": "task",
                "id": "WAA-01:s:task:0",
                "args": {
                    "description": "Explore repository structure",
                    "subagent_type": "explore",
                },
            }
        ],
    }
    out = messages_from_wire_dicts([flat])
    assert len(out) == 1
    assert isinstance(out[0], AIMessageChunk)
    assert out[0].tool_calls[0]["args"]["description"] == "Explore repository structure"
    assert isinstance(out[0].tool_call_chunks[0]["args"], str)
    assert "Explore" in out[0].tool_call_chunks[0]["args"]


def test_envelope_idempotent_message_to_dict() -> None:
    m = AIMessage(content="x")
    good = message_to_dict(m)
    assert envelope_langchain_message_dict(good) is good
    restored = messages_from_dict([good])
    assert isinstance(restored[0], AIMessage)
