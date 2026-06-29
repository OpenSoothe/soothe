"""Unit tests for the protocol-1 client API on WebSocketClient (RFC-450 §5/§9, IG-522 Phase 5).

Covers:
- ``request()``: envelope construction, id correlation, response matching
- ``request()``: error handling (ProtocolError on error envelope)
- ``request()``: timeout when no matching response arrives
- ``request()``: connection-closed detection
- ``notify()``: fire-and-forget (no id, no response wait)
- ``subscribe()``: returns subscription id, sends correct envelope
- ``subscribe()``: raises ProtocolError on immediate rejection
- ``unsubscribe()``: sends correct envelope with matching id
- ``next()``: returns payload for ``next`` messages
- ``next()``: returns full envelope for non-next messages (response/error/complete)
- ``next()``: returns None on EOF
- ``_next_request_id()``: uniqueness
- Backward-compat wrappers delegate to request()/notify()
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_sdk.client.websocket import WebSocketClient
from soothe_sdk.client.wire import ProtocolError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connected_client() -> WebSocketClient:
    """Create a WebSocketClient with a mocked open WebSocket connection."""
    from websockets.asyncio.connection import State

    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()
    client._ws.state = State.OPEN
    client._ws.send = AsyncMock()
    return client


class _EventQueueClient(WebSocketClient):
    """Client whose ``_read_inbound_event`` pops from a pre-seeded queue."""

    def __init__(self) -> None:
        super().__init__()
        self._connected = True
        self._mock_events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def _read_inbound_event(self) -> dict[str, Any] | None:  # type: ignore[override]
        return await self._mock_events.get()

    def is_connection_alive(self) -> bool:  # type: ignore[override]
        return True


# ---------------------------------------------------------------------------
# _next_request_id
# ---------------------------------------------------------------------------


def test_next_request_id_returns_unique_hex() -> None:
    """_next_request_id returns a 32-char hex string, unique across calls."""
    client = WebSocketClient()
    ids = {client._next_request_id() for _ in range(100)}
    assert len(ids) == 100
    for rid in ids:
        assert len(rid) == 32
        int(rid, 16)  # must be valid hex


# ---------------------------------------------------------------------------
# request()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_sends_correct_envelope() -> None:
    """request() sends a WireEnvelope with type='request', method, params, id."""
    client = _make_connected_client()
    sent: list[dict] = []
    client._ws.send = AsyncMock(side_effect=lambda text: sent.append(json.loads(text)))  # type: ignore

    # Seed a matching response so request() doesn't hang.
    client._read_inbound_event = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "proto": "1",
            "type": "response",
            "result": {"loop_id": "abc"},
            "id": sent[0]["id"] if sent else "x",
        }
    )
    # Re-seed: we need the response id to match, so use a two-step approach.
    call_count = 0
    captured_id = ""

    async def mock_read() -> dict[str, Any] | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "proto": "1",
                "type": "response",
                "result": {"loop_id": "abc"},
                "id": captured_id,
            }
        return None

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    # Patch send to capture the id before the response is read.
    async def capture_send(text: str) -> None:
        nonlocal captured_id
        msg = json.loads(text)
        captured_id = msg["id"]

    client._ws.send = AsyncMock(side_effect=capture_send)  # type: ignore

    result = await client.request("loop_get", {"loop_id": "abc"})

    # Verify the sent envelope
    client._ws.send.assert_awaited_once()
    sent_text = client._ws.send.call_args[0][0]
    sent_msg = json.loads(sent_text)
    assert sent_msg["proto"] == "1"
    assert sent_msg["type"] == "request"
    assert sent_msg["method"] == "loop_get"
    assert sent_msg["params"] == {"loop_id": "abc"}
    assert "id" in sent_msg
    assert len(sent_msg["id"]) == 32

    # Verify the result
    assert result == {"loop_id": "abc"}


@pytest.mark.asyncio
async def test_request_correlates_by_id() -> None:
    """request() matches the response by id, ignoring unrelated events."""
    client = _EventQueueClient()
    sent_ids: list[str] = []

    async def capture_send(text: str) -> None:
        msg = json.loads(text)
        sent_ids.append(msg["id"])

    client._ws = MagicMock()
    client._ws.state = MagicMock()
    from websockets.asyncio.connection import State

    client._ws.state = State.OPEN
    client._ws.send = AsyncMock(side_effect=capture_send)

    # Seed: an unrelated event first, then the matching response.
    req_id_holder: dict[str, str] = {}

    async def mock_read() -> dict[str, Any] | None:
        if not req_id_holder:
            return None
        return {
            "proto": "1",
            "type": "response",
            "result": {"ok": True},
            "id": req_id_holder["id"],
        }

    async def capture_send2(text: str) -> None:
        msg = json.loads(text)
        req_id_holder["id"] = msg["id"]

    client._ws.send = AsyncMock(side_effect=capture_send2)  # type: ignore
    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    result = await client.request("daemon_status", {})
    assert result == {"ok": True}
    assert len(req_id_holder["id"]) == 32


@pytest.mark.asyncio
async def test_request_raises_protocol_error_on_error_response() -> None:
    """request() raises ProtocolError when the daemon returns an error envelope."""
    client = _EventQueueClient()
    req_id_holder: dict[str, str] = {}

    async def capture_send(text: str) -> None:
        msg = json.loads(text)
        req_id_holder["id"] = msg["id"]

    from websockets.asyncio.connection import State

    client._ws = MagicMock()
    client._ws.state = State.OPEN
    client._ws.send = AsyncMock(side_effect=capture_send)

    async def mock_read() -> dict[str, Any] | None:
        return {
            "proto": "1",
            "type": "error",
            "error": {
                "code": -32200,
                "message": "Loop not found",
                "data": {"loop_id": "missing"},
            },
            "id": req_id_holder["id"],
        }

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    with pytest.raises(ProtocolError) as exc_info:
        await client.request("loop_get", {"loop_id": "missing"})

    assert exc_info.value.code == -32200
    assert "Loop not found" in exc_info.value.message
    assert exc_info.value.data == {"loop_id": "missing"}


@pytest.mark.asyncio
async def test_request_raises_timeout_error() -> None:
    """request() raises TimeoutError when no matching response arrives in time."""
    client = _make_connected_client()

    async def mock_read() -> dict[str, Any] | None:
        await asyncio.sleep(10)  # Never returns within the timeout.
        return None

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    with pytest.raises(TimeoutError, match="did not respond"):
        await client.request("loop_get", {"loop_id": "abc"}, timeout=0.05)


@pytest.mark.asyncio
async def test_request_raises_connection_error_on_closed_socket() -> None:
    """request() raises ConnectionError when the socket closes while waiting."""
    client = _make_connected_client()

    async def mock_read() -> dict[str, Any] | None:
        return None  # EOF

    client._read_inbound_event = mock_read  # type: ignore[method-assign]
    client.is_connection_alive = lambda: False  # type: ignore[method-assign]

    with pytest.raises(ConnectionError, match="Connection closed"):
        await client.request("loop_get", {"loop_id": "abc"}, timeout=1.0)


@pytest.mark.asyncio
async def test_request_queues_unrelated_events() -> None:
    """request() re-queues events that don't match the request id."""
    client = _EventQueueClient()
    req_id_holder: dict[str, str] = {}

    async def capture_send(text: str) -> None:
        msg = json.loads(text)
        req_id_holder["id"] = msg["id"]

    from websockets.asyncio.connection import State

    client._ws = MagicMock()
    client._ws.state = State.OPEN
    client._ws.send = AsyncMock(side_effect=capture_send)

    events = [
        # Unrelated event (different id)
        {"proto": "1", "type": "next", "id": "other_sub", "payload": {"x": 1}},
        # Matching response
        {"proto": "1", "type": "response", "result": {"ok": True}, "id": "PLACEHOLDER"},
    ]
    event_iter = iter(events)

    async def mock_read() -> dict[str, Any] | None:
        try:
            ev = next(event_iter)
            if ev["id"] == "PLACEHOLDER":
                ev["id"] = req_id_holder["id"]
            return ev
        except StopIteration:
            return None

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    result = await client.request("daemon_status", {})
    assert result == {"ok": True}

    # The unrelated event should have been re-queued.
    assert len(client._pending_events) == 1
    assert client._pending_events[0]["type"] == "next"


# ---------------------------------------------------------------------------
# notify()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_sends_envelope_without_id() -> None:
    """notify() sends a notification envelope with no id field."""
    client = _make_connected_client()
    sent: list[dict] = []
    client._ws.send = AsyncMock(side_effect=lambda text: sent.append(json.loads(text)))  # type: ignore

    await client.notify("loop_input", {"loop_id": "abc", "content": "hello"})

    assert len(sent) == 1
    msg = sent[0]
    assert msg["proto"] == "1"
    assert msg["type"] == "notification"
    assert msg["method"] == "loop_input"
    assert msg["params"] == {"loop_id": "abc", "content": "hello"}
    assert "id" not in msg


@pytest.mark.asyncio
async def test_notify_does_not_wait_for_response() -> None:
    """notify() returns immediately without reading inbound events."""
    client = _make_connected_client()
    client._ws.send = AsyncMock()
    client._read_inbound_event = AsyncMock()  # type: ignore[method-assign]

    await client.notify("disconnect", {})

    # _read_inbound_event should never have been called.
    client._read_inbound_event.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_notify_raises_connection_error_when_not_connected() -> None:
    """notify() raises ConnectionError when not connected."""
    client = WebSocketClient()
    client._connected = False

    with pytest.raises(ConnectionError):
        await client.notify("loop_input", {})


# ---------------------------------------------------------------------------
# subscribe()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_sends_envelope_and_returns_id() -> None:
    """subscribe() sends a subscribe envelope and returns the subscription id."""
    client = _make_connected_client()
    sent: list[dict] = []
    client._ws.send = AsyncMock(side_effect=lambda text: sent.append(json.loads(text)))  # type: ignore

    # No error arrives — subscription assumed accepted after timeout.
    async def mock_read() -> dict[str, Any] | None:
        await asyncio.sleep(10)
        return None

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    sub_id = await client.subscribe("loop_events", {"loop_id": "abc"}, timeout=0.05)

    assert len(sent) == 1
    msg = sent[0]
    assert msg["proto"] == "1"
    assert msg["type"] == "subscribe"
    assert msg["method"] == "loop_events"
    assert msg["params"] == {"loop_id": "abc"}
    assert msg["id"] == sub_id
    assert len(sub_id) == 32


@pytest.mark.asyncio
async def test_subscribe_raises_protocol_error_on_rejection() -> None:
    """subscribe() raises ProtocolError when daemon sends error with matching id."""
    client = _EventQueueClient()
    sub_id_holder: dict[str, str] = {}

    async def capture_send(text: str) -> None:
        msg = json.loads(text)
        sub_id_holder["id"] = msg["id"]

    from websockets.asyncio.connection import State

    client._ws = MagicMock()
    client._ws.state = State.OPEN
    client._ws.send = AsyncMock(side_effect=capture_send)

    async def mock_read() -> dict[str, Any] | None:
        return {
            "proto": "1",
            "type": "error",
            "error": {
                "code": -32200,
                "message": "Loop not found",
            },
            "id": sub_id_holder["id"],
        }

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    with pytest.raises(ProtocolError) as exc_info:
        await client.subscribe("loop_events", {"loop_id": "missing"}, timeout=1.0)

    assert exc_info.value.code == -32200
    assert "Loop not found" in exc_info.value.message


@pytest.mark.asyncio
async def test_subscribe_accepts_next_event_as_confirmation() -> None:
    """subscribe() returns immediately when a next event arrives for the sub id."""
    client = _EventQueueClient()
    sub_id_holder: dict[str, str] = {}

    async def capture_send(text: str) -> None:
        msg = json.loads(text)
        sub_id_holder["id"] = msg["id"]

    from websockets.asyncio.connection import State

    client._ws = MagicMock()
    client._ws.state = State.OPEN
    client._ws.send = AsyncMock(side_effect=capture_send)

    async def mock_read() -> dict[str, Any] | None:
        return {
            "proto": "1",
            "type": "next",
            "id": sub_id_holder["id"],
            "payload": {"namespace": "assistant", "data": "hi"},
        }

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    sub_id = await client.subscribe("loop_events", {"loop_id": "abc"}, timeout=5.0)
    assert sub_id == sub_id_holder["id"]
    # The next event was re-queued for the consumer to read via next().
    assert len(client._pending_events) == 1


# ---------------------------------------------------------------------------
# unsubscribe()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsubscribe_sends_correct_envelope() -> None:
    """unsubscribe() sends an unsubscribe envelope with the subscription id."""
    client = _make_connected_client()
    sent: list[dict] = []
    client._ws.send = AsyncMock(side_effect=lambda text: sent.append(json.loads(text)))  # type: ignore

    await client.unsubscribe("sub_123")

    assert len(sent) == 1
    msg = sent[0]
    assert msg["proto"] == "1"
    assert msg["type"] == "unsubscribe"
    assert msg["id"] == "sub_123"
    assert "method" not in msg
    assert "params" not in msg or msg["params"] is None or msg.get("params") is None


@pytest.mark.asyncio
async def test_unsubscribe_raises_connection_error_when_not_connected() -> None:
    """unsubscribe() raises ConnectionError when not connected."""
    client = WebSocketClient()
    client._connected = False

    with pytest.raises(ConnectionError):
        await client.unsubscribe("sub_123")


# ---------------------------------------------------------------------------
# next()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_returns_payload_for_next_message() -> None:
    """next() returns the payload dict for type='next' messages."""
    client = _make_connected_client()

    payload = {"namespace": "assistant", "mode": "text", "data": "Hello!"}

    async def mock_read() -> dict[str, Any] | None:
        return {"proto": "1", "type": "next", "id": "s1", "payload": payload}

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    result = await client.next()
    assert result == payload


@pytest.mark.asyncio
async def test_next_returns_full_envelope_for_response() -> None:
    """next() returns the full envelope for non-next messages (response)."""
    client = _make_connected_client()

    envelope = {"proto": "1", "type": "response", "result": {"ok": True}, "id": "r1"}

    async def mock_read() -> dict[str, Any] | None:
        return envelope

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    result = await client.next()
    assert result == envelope


@pytest.mark.asyncio
async def test_next_returns_full_envelope_for_error() -> None:
    """next() returns the full envelope for error messages."""
    client = _make_connected_client()

    envelope = {
        "proto": "1",
        "type": "error",
        "error": {"code": -32603, "message": "oops"},
        "id": "r1",
    }

    async def mock_read() -> dict[str, Any] | None:
        return envelope

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    result = await client.next()
    assert result == envelope


@pytest.mark.asyncio
async def test_next_returns_full_envelope_for_complete() -> None:
    """next() returns the full envelope for complete messages."""
    client = _make_connected_client()

    envelope = {"proto": "1", "type": "complete", "id": "s1"}

    async def mock_read() -> dict[str, Any] | None:
        return envelope

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    result = await client.next()
    assert result == envelope


@pytest.mark.asyncio
async def test_next_returns_none_on_eof() -> None:
    """next() returns None when the connection is closed (EOF)."""
    client = _make_connected_client()

    async def mock_read() -> dict[str, Any] | None:
        return None

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    result = await client.next()
    assert result is None


@pytest.mark.asyncio
async def test_next_returns_pending_events_first() -> None:
    """next() drains pending events before reading from the socket."""
    client = _make_connected_client()

    pending = {"proto": "1", "type": "next", "id": "s1", "payload": {"queued": True}}
    client._pending_events.append(pending)

    # This should never be called because pending events come first.
    async def mock_read() -> dict[str, Any] | None:
        raise AssertionError("should not read from socket with pending events")

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    result = await client.next()
    assert result == {"queued": True}
    assert len(client._pending_events) == 0


# ---------------------------------------------------------------------------
# Backward-compat wrappers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_input_delegates_to_notify() -> None:
    """send_input delegates to notify() with method='loop_input'."""
    client = _make_connected_client()
    sent: list[dict] = []
    client._ws.send = AsyncMock(side_effect=lambda text: sent.append(json.loads(text)))  # type: ignore

    await client.send_input("loop-1", "hello", clarification_mode="manual")

    assert len(sent) == 1
    msg = sent[0]
    assert msg["type"] == "notification"
    assert msg["method"] == "loop_input"
    assert msg["params"]["loop_id"] == "loop-1"
    assert msg["params"]["content"] == "hello"
    assert msg["params"]["clarification_mode"] == "manual"
    assert "id" not in msg
