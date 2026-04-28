"""Tests for daemon WebSocket message normalization in the TUI."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, messages_from_dict
from soothe_sdk.client.protocol import _serialize_for_json
from soothe_sdk.langchain_wire import envelope_langchain_message_dict

from soothe_cli.tui.daemon_session import TuiDaemonSession


class _StubEventClient:
    def __init__(self, events: list[dict]) -> None:
        self._events = list(events)

    async def read_event(self) -> dict | None:
        if not self._events:
            return None
        return self._events.pop(0)


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


@pytest.mark.asyncio
async def test_get_thread_messages_uses_request_response_and_filters_rows() -> None:
    """Thread message RPC should run under read lock and return only dict rows."""
    session = object.__new__(TuiDaemonSession)
    request_response = AsyncMock(
        return_value={
            "messages": [
                {"kind": "event", "content": "x"},
                "not-a-dict",
                {"kind": "conversation", "content": "hello"},
            ]
        }
    )
    session._client = type("StubClient", (), {"request_response": request_response})()
    session._read_lock = asyncio.Lock()

    result = await session.get_thread_messages(
        "thread-123",
        limit=50,
        offset=3,
        include_events=True,
    )

    request_response.assert_awaited_once_with(
        {
            "type": "thread_messages",
            "thread_id": "thread-123",
            "limit": 50,
            "offset": 3,
            "include_events": True,
        },
        response_type="thread_messages_response",
        timeout=10.0,
    )
    assert result == [
        {"kind": "event", "content": "x"},
        {"kind": "conversation", "content": "hello"},
    ]


@pytest.mark.asyncio
async def test_get_thread_messages_returns_empty_without_thread_id() -> None:
    """Empty thread IDs should short-circuit without RPC."""
    session = object.__new__(TuiDaemonSession)
    request_response = AsyncMock()
    session._client = type("StubClient", (), {"request_response": request_response})()
    session._read_lock = asyncio.Lock()

    assert await session.get_thread_messages("", include_events=True) == []
    request_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_iter_turn_chunks_filters_non_active_thread_events() -> None:
    """Daemon turn stream should ignore events from other thread IDs."""
    session = object.__new__(TuiDaemonSession)
    session._thread_id = "thread-main"
    session._read_lock = asyncio.Lock()
    session._streaming = False
    session._client = _StubEventClient(
        [
            {"type": "status", "state": "running", "thread_id": "thread-other"},
            {
                "type": "event",
                "thread_id": "thread-other",
                "namespace": [],
                "mode": "messages",
                "data": ("other", {}),
            },
            {"type": "status", "state": "running", "thread_id": "thread-main"},
            {
                "type": "event",
                "thread_id": "thread-main",
                "namespace": [],
                "mode": "messages",
                "data": ("main", {}),
            },
            {"type": "status", "state": "idle", "thread_id": "thread-other"},
            {"type": "status", "state": "idle", "thread_id": "thread-main"},
        ]
    )

    chunks = [chunk async for chunk in session.iter_turn_chunks()]

    assert chunks == [((), "messages", ("main", {}))]
    assert session._thread_id == "thread-main"
