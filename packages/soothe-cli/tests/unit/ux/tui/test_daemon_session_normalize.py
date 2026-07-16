"""Tests for daemon WebSocket message normalization in the TUI."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, messages_from_dict
from soothe_client.websocket import WebSocketClient
from soothe_sdk.langchain_wire import envelope_langchain_message_dict
from soothe_sdk.wire.protocol import _serialize_for_json

from soothe_cli.runtime.transport.session import TuiDaemonSession


class _StubEventClient:
    def __init__(self, events: list[dict]) -> None:
        self._events = list(events)

    def peel_stale_pending_control_events(self) -> list[str]:
        removed: list[str] = []
        kept: list[dict] = []
        stale = WebSocketClient._STALE_TURN_PENDING_TYPES  # noqa: SLF001
        for event in self._events:
            event_type = str(event.get("type") or "")
            if event_type in stale:
                removed.append(event_type)
            else:
                kept.append(event)
        self._events = kept
        return removed

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
    """IG-440: AIMessageChunk identity is preserved on the wire.

    Pre-IG-440 the wire collapsed ``AIMessageChunk`` → ``ai`` so the client
    restored it as plain ``AIMessage``. That broke the TUI synthesis stream
    branch (``isinstance(msg, AIMessageChunk)``), silently dropping every
    chunk after the first. The fix keeps the chunk tag intact end-to-end.
    """
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


def test_normalize_lc_stream_message_restores_ai_message() -> None:
    """``normalize_lc_stream_message`` must yield AIMessage for flat wire dicts."""
    from soothe_cli.runtime.wire.messages import normalize_lc_stream_message

    flat = _serialize_for_json(AIMessage(content="wire"))
    msg = normalize_lc_stream_message(flat)
    assert isinstance(msg, AIMessage)
    assert msg.content == "wire"


@pytest.mark.asyncio
async def test_fetch_conversation_log_uses_request_and_filters_rows() -> None:
    """Conversation log RPC should run under RPC lock and return only dict rows."""
    session = object.__new__(TuiDaemonSession)
    request = AsyncMock(
        return_value={
            "messages": [
                {"kind": "event", "content": "x"},
                "not-a-dict",
                {"kind": "conversation", "content": "hello"},
            ]
        }
    )
    session._rpc_client = type("StubClient", (), {"request": request})()
    session._rpc_lock = asyncio.Lock()
    session._rpc_connected = True
    session._ensure_rpc_connected = AsyncMock()

    result = await session.fetch_conversation_log(
        "thread-123",
        limit=50,
        offset=3,
        include_events=True,
    )

    request.assert_awaited_once_with(
        "loop_messages",
        {
            "loop_id": "thread-123",
            "limit": 50,
            "offset": 3,
            "include_events": True,
        },
        timeout=10.0,
    )
    assert result == [
        {"kind": "event", "content": "x"},
        {"kind": "conversation", "content": "hello"},
    ]


@pytest.mark.asyncio
async def test_fetch_conversation_log_returns_empty_without_id() -> None:
    """Empty conversation ids should short-circuit without RPC."""
    session = object.__new__(TuiDaemonSession)
    request = AsyncMock()
    session._rpc_client = type("StubClient", (), {"request": request})()
    session._rpc_lock = asyncio.Lock()

    assert await session.fetch_conversation_log("", include_events=True) == []
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_iter_turn_chunks_filters_non_active_loop_events() -> None:
    """Daemon turn stream should ignore events from other loop ids."""
    session = object.__new__(TuiDaemonSession)
    session._loop_id = "loop-main"
    session._read_lock = asyncio.Lock()
    session._streaming = False
    session._client = _StubEventClient(
        [
            {"type": "status", "state": "running", "loop_id": "loop-other"},
            {
                "type": "event",
                "loop_id": "loop-other",
                "namespace": [],
                "mode": "messages",
                "data": ("other", {}),
            },
            {"type": "status", "state": "running", "loop_id": "loop-main"},
            {
                "type": "event",
                "loop_id": "loop-main",
                "namespace": [],
                "mode": "messages",
                "data": ("main", {}),
            },
            {"type": "status", "state": "idle", "loop_id": "loop-other"},
            {"type": "status", "state": "idle", "loop_id": "loop-main"},
        ]
    )

    chunks = [chunk async for chunk in session.iter_turn_chunks()]

    assert chunks == [((), "messages", ("main", {}))]
    assert session._loop_id == "loop-main"


@pytest.mark.asyncio
async def test_iter_turn_chunks_peels_stale_daemon_ready_before_stream() -> None:
    """Stale ``daemon_ready`` in the read path must not hide a missing live stream."""
    session = object.__new__(TuiDaemonSession)
    session._loop_id = "loop-main"
    session._read_lock = asyncio.Lock()
    session._streaming = False
    session.turn_event_stats = None
    session._client = _StubEventClient(
        [
            {"type": "daemon_ready", "state": "ready"},
            {"type": "status", "state": "running", "loop_id": "loop-main"},
            {
                "type": "event",
                "loop_id": "loop-main",
                "namespace": [],
                "mode": "custom",
                "data": {"type": "soothe.cognition.strange_loop.started"},
            },
            {"type": "status", "state": "idle", "loop_id": "loop-main"},
        ]
    )

    chunks = [chunk async for chunk in session.iter_turn_chunks()]

    assert len(chunks) == 1
    assert chunks[0][1] == "custom"


@pytest.mark.asyncio
async def test_iter_turn_chunks_drains_events_after_idle() -> None:
    """Late stream frames after ``idle`` should be consumed (headless CLI parity)."""
    session = object.__new__(TuiDaemonSession)
    session._loop_id = "loop-main"
    session._read_lock = asyncio.Lock()
    session._streaming = False
    session._client = _StubEventClient(
        [
            {"type": "status", "state": "running", "loop_id": "loop-main"},
            {
                "type": "event",
                "loop_id": "loop-main",
                "namespace": [],
                "mode": "messages",
                "data": ("first", {}),
            },
            {"type": "status", "state": "idle", "loop_id": "loop-main"},
            {
                "type": "event",
                "loop_id": "loop-main",
                "namespace": [],
                "mode": "messages",
                "data": ("late", {}),
            },
            {"type": "status", "state": "idle", "loop_id": "loop-main"},
        ]
    )

    chunks = [chunk async for chunk in session.iter_turn_chunks()]

    assert chunks == [
        ((), "messages", ("first", {})),
        ((), "messages", ("late", {})),
    ]


@pytest.mark.asyncio
async def test_iter_turn_chunks_ignores_stale_idle_before_stream_payload() -> None:
    """Stale ``idle`` from a cancelled predecessor turn must not end the read session."""
    session = object.__new__(TuiDaemonSession)
    session._loop_id = "loop-main"
    session._read_lock = asyncio.Lock()
    session._streaming = False
    session._client = _StubEventClient(
        [
            {"type": "status", "state": "running", "loop_id": "loop-main"},
            {"type": "status", "state": "idle", "loop_id": "loop-main"},
            {
                "type": "event",
                "loop_id": "loop-main",
                "namespace": [],
                "mode": "messages",
                "data": ("successor", {}),
            },
            {"type": "status", "state": "idle", "loop_id": "loop-main"},
        ]
    )

    chunks = [chunk async for chunk in session.iter_turn_chunks()]

    assert chunks == [((), "messages", ("successor", {}))]
    assert session.last_turn_end_state == "idle"


@pytest.mark.asyncio
async def test_ensure_rpc_connected_completes_protocol_handshake() -> None:
    """Metadata RPC socket must handshake before skills_list and similar calls."""
    session = object.__new__(TuiDaemonSession)
    session._rpc_connected = False
    session._rpc_client = AsyncMock()

    with patch(
        "soothe_client.appkit.daemon_session.connect_websocket_with_retries",
        new_callable=AsyncMock,
    ) as connect_mock:
        await session._ensure_rpc_connected()

    connect_mock.assert_awaited_once_with(session._rpc_client)
    session._rpc_client.request_connection_init.assert_awaited_once()
    session._rpc_client.wait_for_connection_ack.assert_awaited_once_with(ack_timeout_s=20.0)
    assert session._rpc_connected is True


@pytest.mark.asyncio
async def test_close_is_idempotent_and_closes_both_sockets_in_parallel() -> None:
    """TUI teardown may call close twice; both clients should close once each."""
    session = object.__new__(TuiDaemonSession)
    session._closed = False
    session._client = AsyncMock()
    session._rpc_client = AsyncMock()
    session._rpc_connected = True

    await session.close(handshake_timeout=0.3)
    await session.close(handshake_timeout=0.3)

    session._client.close.assert_awaited_once_with(handshake_timeout=0.3)
    session._rpc_client.close.assert_awaited_once_with(handshake_timeout=0.3)
    assert session._closed is True
    assert session._rpc_connected is False


@pytest.mark.asyncio
async def test_ensure_rpc_connected_skips_when_already_connected() -> None:
    """Second RPC call should not repeat connect or handshake."""
    session = object.__new__(TuiDaemonSession)
    session._rpc_connected = True
    session._rpc_client = AsyncMock()

    with patch(
        "soothe_client.appkit.daemon_session.connect_websocket_with_retries",
        new_callable=AsyncMock,
    ) as connect_mock:
        await session._ensure_rpc_connected()

    connect_mock.assert_not_awaited()
    session._rpc_client.request_connection_init.assert_not_awaited()
    session._rpc_client.wait_for_connection_ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_iter_turn_chunks_records_cancellation_command() -> None:
    """``command_response`` cancel notices should be tracked for stream-end UX."""
    session = object.__new__(TuiDaemonSession)
    session._loop_id = "loop-main"
    session._read_lock = asyncio.Lock()
    session._streaming = False
    session._client = _StubEventClient(
        [
            {"type": "status", "state": "running", "loop_id": "loop-main"},
            {
                "type": "command_response",
                "loop_id": "loop-main",
                "content": "[yellow]Cancellation requested.[/yellow]",
            },
            {"type": "status", "state": "idle", "loop_id": "loop-main"},
        ]
    )

    _ = [chunk async for chunk in session.iter_turn_chunks()]

    assert session.last_turn_cancellation_seen is True
    assert session.last_turn_end_state == "idle"


@pytest.mark.asyncio
async def test_iter_turn_chunks_records_stopped_end_state() -> None:
    """Stopped status after payload should end the turn."""
    session = object.__new__(TuiDaemonSession)
    session._loop_id = "loop-main"
    session._read_lock = asyncio.Lock()
    session._streaming = False
    session._client = _StubEventClient(
        [
            {"type": "status", "state": "running", "loop_id": "loop-main"},
            {
                "type": "event",
                "loop_id": "loop-main",
                "namespace": [],
                "mode": "custom",
                "data": {"type": "soothe.test.payload"},
            },
            {"type": "status", "state": "stopped", "loop_id": "loop-main"},
        ]
    )

    _ = [chunk async for chunk in session.iter_turn_chunks()]

    assert session.last_turn_end_state == "stopped"
    assert session.last_turn_cancellation_seen is False


@pytest.mark.asyncio
async def test_iter_turn_chunks_ends_on_terminal_custom_without_idle_status() -> None:
    """Terminal custom events should end the turn even without trailing idle/stopped."""
    session = object.__new__(TuiDaemonSession)
    session._loop_id = "loop-main"
    session._read_lock = asyncio.Lock()
    session._streaming = False
    session._client = _StubEventClient(
        [
            {"type": "status", "state": "running", "loop_id": "loop-main"},
            {
                "type": "event",
                "loop_id": "loop-main",
                "namespace": [],
                "mode": "custom",
                "data": {"type": "soothe.cognition.strange_loop.completed"},
            },
            {
                "type": "event",
                "loop_id": "loop-main",
                "namespace": [],
                "mode": "messages",
                "data": ("late", {}),
            },
            # Simulate missing terminal status event from daemon.
        ]
    )

    chunks = [chunk async for chunk in session.iter_turn_chunks()]

    assert chunks == [
        ((), "custom", {"type": "soothe.cognition.strange_loop.completed"}),
        ((), "messages", ("late", {})),
    ]
    assert session.last_turn_end_state == "completed"
