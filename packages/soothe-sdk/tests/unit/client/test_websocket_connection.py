"""Tests for WebSocket client connection and handshake handling (RFC-450 §8.2).

These tests cover the protocol-1 ``connection_init`` / ``connection_ack``
handshake that replaces the legacy one-way ``daemon_ready`` flow.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_sdk.client.websocket import WebSocketClient

# ---------------------------------------------------------------------------
# request_connection_init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_connection_init_sends_correct_envelope() -> None:
    """request_connection_init sends a connection_init envelope with proto '1'."""
    client = WebSocketClient()
    client._connected = True
    sent: list[dict] = []
    client.send = AsyncMock(side_effect=lambda msg: sent.append(msg))  # type: ignore[method-assign]

    await client.request_connection_init()

    assert len(sent) == 1
    msg = sent[0]
    assert msg["proto"] == "1"
    assert msg["type"] == "connection_init"
    params = msg["params"]
    assert params["accept_proto"] == ["1"]
    assert "streaming" in params["capabilities"]
    assert "batch" in params["capabilities"]
    assert "heartbeat" in params["capabilities"]


@pytest.mark.asyncio
async def test_request_connection_init_handles_closed_connection() -> None:
    """request_connection_init should not raise on ConnectionError (handshake may have sent it)."""
    client = WebSocketClient()
    client._connected = False  # Simulate closed connection

    # Should not raise
    await client.request_connection_init()


# ---------------------------------------------------------------------------
# wait_for_connection_ack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_connection_ack_can_use_pending_handshake_event() -> None:
    """wait_for_connection_ack should work with connection_ack from pending events."""
    client = WebSocketClient()
    client._connected = True

    ack_event = {
        "proto": "1",
        "type": "connection_ack",
        "result": {
            "server_version": "0.5.0",
            "protocol_version": "1",
            "capabilities": ["streaming", "batch", "heartbeat"],
            "readiness_state": "ready",
            "heartbeat_interval_ms": 30000,
        },
    }
    client._pending_events.append(ack_event)

    result = await client.wait_for_connection_ack(ack_timeout_s=0.5)
    assert result == ack_event
    assert client._handshake_complete is True
    assert client._protocol_version == "1"
    assert "streaming" in client._negotiated_capabilities


@pytest.mark.asyncio
async def test_wait_for_connection_ack_handles_warming_then_ready() -> None:
    """wait_for_connection_ack should poll through transitional states."""
    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()

    events = [
        {
            "proto": "1",
            "type": "connection_ack",
            "result": {"readiness_state": "warming", "protocol_version": "1"},
        },
        {
            "proto": "1",
            "type": "connection_ack",
            "result": {"readiness_state": "ready", "protocol_version": "1"},
        },
    ]

    event_iter = iter(events)

    async def mock_read() -> dict | None:
        try:
            return next(event_iter)  # type: ignore[no-any-return]
        except StopIteration:
            return None

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    result = await client.wait_for_connection_ack(ack_timeout_s=1.0)
    assert result["result"]["readiness_state"] == "ready"


@pytest.mark.asyncio
async def test_wait_for_connection_ack_raises_on_error_state() -> None:
    """wait_for_connection_ack should raise RuntimeError on error state."""
    client = WebSocketClient()
    client._connected = True

    error_event = {
        "proto": "1",
        "type": "connection_ack",
        "result": {"readiness_state": "error", "server_version": "0.5.0"},
    }
    client._pending_events.append(error_event)

    with pytest.raises(RuntimeError):
        await client.wait_for_connection_ack(ack_timeout_s=0.5)


@pytest.mark.asyncio
async def test_wait_for_connection_ack_raises_on_degraded_state() -> None:
    """wait_for_connection_ack should raise RuntimeError on degraded state."""
    client = WebSocketClient()
    client._connected = True

    degraded_event = {
        "proto": "1",
        "type": "connection_ack",
        "result": {"readiness_state": "degraded", "server_version": "0.5.0"},
    }
    client._pending_events.append(degraded_event)

    with pytest.raises(RuntimeError, match="degraded"):
        await client.wait_for_connection_ack(ack_timeout_s=0.5)


@pytest.mark.asyncio
async def test_wait_for_connection_ack_raises_on_incompatible_state() -> None:
    """wait_for_connection_ack should raise ConnectionError on incompatible state."""
    client = WebSocketClient()
    client._connected = True

    incompatible_event = {
        "proto": "1",
        "type": "connection_ack",
        "result": {"readiness_state": "incompatible", "server_version": "0.5.0"},
    }
    client._pending_events.append(incompatible_event)

    with pytest.raises(ConnectionError, match="incompatible"):
        await client.wait_for_connection_ack(ack_timeout_s=0.5)


@pytest.mark.asyncio
async def test_wait_for_connection_ack_raises_when_connection_closed() -> None:
    """wait_for_connection_ack should surface a closed socket as ConnectionError."""
    client = WebSocketClient()
    client._connected = False

    with pytest.raises(ConnectionError, match="Connection closed"):
        await client.wait_for_connection_ack(ack_timeout_s=0.5)


@pytest.mark.asyncio
async def test_wait_for_connection_ack_skips_handshake_status_in_inbound_queue() -> None:
    """Handshake status must not block connection_ack when using the background reader."""
    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()
    handshake_status = {"type": "status", "state": "idle", "input_history": []}
    connection_ack = {
        "proto": "1",
        "type": "connection_ack",
        "result": {"readiness_state": "ready", "protocol_version": "1"},
    }
    client._read_from_socket = AsyncMock(  # type: ignore[method-assign]
        side_effect=[handshake_status, connection_ack, None]
    )
    client._reader_task = asyncio.create_task(client._socket_reader_loop())
    await asyncio.sleep(0.05)

    result = await client.wait_for_connection_ack(ack_timeout_s=1.0)
    assert result["result"]["readiness_state"] == "ready"
    assert len(client._pending_events) == 0

    await client.close()


# ---------------------------------------------------------------------------
# Backward-compatible aliases
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# send() error path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_raises_when_socket_not_open() -> None:
    """send() should fail fast when the transport is no longer open."""
    from websockets.asyncio.connection import State

    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()
    client._ws.state = State.CLOSED

    with pytest.raises(ConnectionError, match="Connection closed"):
        await client.send({"type": "ping"})


# ---------------------------------------------------------------------------
# connect() cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_closes_existing_socket_before_reconnect() -> None:
    """connect() must not leak a previous websocket when reconnecting."""
    client = WebSocketClient()
    old_ws = AsyncMock()
    client._ws = old_ws
    client._connected = True

    new_ws = AsyncMock()
    connect_mock = AsyncMock(return_value=new_ws)

    import websockets.asyncio.client as ws_client_mod

    original_connect = ws_client_mod.connect
    ws_client_mod.connect = connect_mock
    try:
        await client.connect()
        assert client._reader_task is not None
    finally:
        ws_client_mod.connect = original_connect
        await client.close()

    old_ws.close.assert_awaited_once()
    assert client._ws is None
    assert client._connected is False
    assert client._reader_task is None


# ---------------------------------------------------------------------------
# peel_stale_pending_control_events
# ---------------------------------------------------------------------------


def test_peel_stale_pending_control_events() -> None:
    """Handshake/RPC leftovers must not block turn progress detection."""
    client = WebSocketClient()
    client._pending_events.append({"type": "connection_ack"})
    # Under protocol-1 card replay frames arrive wrapped in ``next`` envelopes;
    # the peel logic inspects ``payload.mode`` to recognize them as stale.
    client._pending_events.append(
        {
            "type": "next",
            "payload": {"mode": "card.replay_begin", "data": {"type": "card.replay_begin"}},
        }
    )
    client._pending_events.append({"type": "status", "state": "running", "loop_id": "abc"})

    removed = client.peel_stale_pending_control_events()

    assert "connection_ack" in removed
    assert "card.replay_begin" in removed
    assert len(client._pending_events) == 1
    assert client._pending_events[0]["type"] == "status"


# ---------------------------------------------------------------------------
# Background reader delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_background_reader_delivers_events_to_read_event() -> None:
    """Socket reader task should feed read_event without blocking on UI work."""
    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()
    payload = {"type": "status", "state": "running"}
    client._read_from_socket = AsyncMock(side_effect=[payload, None])  # type: ignore[method-assign]
    client._reader_task = asyncio.create_task(client._socket_reader_loop())

    first = await asyncio.wait_for(client.read_event(), timeout=1.0)
    assert first == payload

    await client.close()


# ---------------------------------------------------------------------------
# Heartbeat ping/pong
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_responds_to_daemon_ping_with_pong() -> None:
    """The socket reader loop intercepts ping frames and responds with pong."""
    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()
    sent_frames: list[str] = []

    async def fake_send(data: str) -> None:
        sent_frames.append(data)

    client._ws.send = fake_send

    ping_frame = {"proto": "1", "type": "ping"}
    client._read_from_socket = AsyncMock(side_effect=[ping_frame, None])  # type: ignore[method-assign]
    client._reader_task = asyncio.create_task(client._socket_reader_loop())
    await asyncio.sleep(0.1)

    import json

    assert any(json.loads(f).get("type") == "pong" for f in sent_frames)

    await client.close()


@pytest.mark.asyncio
async def test_client_pong_does_not_enqueue_to_inbound() -> None:
    """A pong frame is swallowed (not enqueued for read_event consumers)."""
    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()

    pong_frame = {"proto": "1", "type": "pong"}
    normal_event = {"type": "status", "state": "running"}
    client._read_from_socket = AsyncMock(side_effect=[pong_frame, normal_event, None])  # type: ignore[method-assign]
    client._reader_task = asyncio.create_task(client._socket_reader_loop())
    await asyncio.sleep(0.1)

    # The first event available should be the status, not pong
    event = await asyncio.wait_for(client.read_event(), timeout=1.0)
    assert event["type"] == "status"

    await client.close()


@pytest.mark.asyncio
async def test_heartbeat_task_started_after_ack() -> None:
    """A heartbeat ping task is started after the connection_ack is received."""
    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()

    ack_event = {
        "proto": "1",
        "type": "connection_ack",
        "result": {
            "readiness_state": "ready",
            "protocol_version": "1",
            "capabilities": ["streaming", "heartbeat"],
            "heartbeat_interval_ms": 50,  # very short for testing
            "server_version": "0.5.0",
        },
    }
    client._pending_events.append(ack_event)

    await client.wait_for_connection_ack(ack_timeout_s=0.5)
    assert client._heartbeat_task is not None
    assert client._heartbeat_interval_ms == 50

    await client.close()


@pytest.mark.asyncio
async def test_heartbeat_task_not_started_without_capability() -> None:
    """No heartbeat task is started if the server doesn't declare heartbeat capability."""
    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()

    ack_event = {
        "proto": "1",
        "type": "connection_ack",
        "result": {
            "readiness_state": "ready",
            "protocol_version": "1",
            "capabilities": ["streaming"],  # no heartbeat
            "heartbeat_interval_ms": 50,
            "server_version": "0.5.0",
        },
    }
    client._pending_events.append(ack_event)

    await client.wait_for_connection_ack(ack_timeout_s=0.5)
    assert client._heartbeat_task is None

    await client.close()


@pytest.mark.asyncio
async def test_close_cancels_heartbeat_task() -> None:
    """close() cancels the heartbeat ping task."""
    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()

    ack_event = {
        "proto": "1",
        "type": "connection_ack",
        "result": {
            "readiness_state": "ready",
            "protocol_version": "1",
            "capabilities": ["streaming", "heartbeat"],
            "heartbeat_interval_ms": 50,
            "server_version": "0.5.0",
        },
    }
    client._pending_events.append(ack_event)

    await client.wait_for_connection_ack(ack_timeout_s=0.5)
    hb = client._heartbeat_task
    assert hb is not None

    await client.close()
    assert client._heartbeat_task is None
    assert hb.cancelled() or hb.done()
