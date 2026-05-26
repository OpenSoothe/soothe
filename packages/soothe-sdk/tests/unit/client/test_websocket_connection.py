"""Tests for WebSocket client connection handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_sdk.client.websocket import WebSocketClient


@pytest.mark.asyncio
async def test_request_daemon_ready_handles_closed_connection() -> None:
    """request_daemon_ready should not raise on ConnectionError (handshake may have sent it)."""
    client = WebSocketClient()
    client._connected = False  # Simulate closed connection

    # Should not raise - the daemon may have sent daemon_ready during handshake
    await client.request_daemon_ready()

    # Verify no exception was raised


@pytest.mark.asyncio
async def test_wait_for_daemon_ready_can_use_pending_handshake_event() -> None:
    """wait_for_daemon_ready should work with daemon_ready from handshake."""
    client = WebSocketClient()
    client._connected = True

    # Simulate daemon sending daemon_ready during handshake
    handshake_event = {"type": "daemon_ready", "state": "ready"}
    client._pending_events.append(handshake_event)

    # Should succeed without needing to read from socket
    result = await client.wait_for_daemon_ready(ready_timeout_s=0.5)

    assert result == handshake_event


@pytest.mark.asyncio
async def test_wait_for_daemon_ready_handles_warming_then_ready() -> None:
    """wait_for_daemon_ready should poll through transitional states."""
    client = WebSocketClient()
    client._connected = True

    # Simulate daemon transitioning from warming to ready
    events = [
        {"type": "daemon_ready", "state": "warming"},
        {"type": "daemon_ready", "state": "ready"},
    ]

    event_iter = iter(events)

    async def mock_read() -> dict[str, None] | None:
        try:
            return next(event_iter)  # type: ignore[no-any-return]
        except StopIteration:
            return None

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    result = await client.wait_for_daemon_ready(ready_timeout_s=0.5)
    assert result["state"] == "ready"


@pytest.mark.asyncio
async def test_wait_for_daemon_ready_raises_on_error_state() -> None:
    """wait_for_daemon_ready should raise RuntimeError on error state."""
    client = WebSocketClient()
    client._connected = True

    # Simulate daemon in error state
    error_event = {"type": "daemon_ready", "state": "error", "message": "startup failed"}
    client._pending_events.append(error_event)

    with pytest.raises(RuntimeError, match="startup failed"):
        await client.wait_for_daemon_ready(ready_timeout_s=0.5)


@pytest.mark.asyncio
async def test_send_raises_when_socket_not_open() -> None:
    """send() should fail fast when the transport is no longer open."""
    from websockets.asyncio.connection import State

    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()
    client._ws.state = State.CLOSED

    with pytest.raises(ConnectionError, match="Connection closed"):
        await client.send({"type": "daemon_ready"})


@pytest.mark.asyncio
async def test_wait_for_daemon_ready_raises_when_connection_closed() -> None:
    """wait_for_daemon_ready should surface a closed socket as ConnectionError."""
    client = WebSocketClient()
    client._connected = False

    with pytest.raises(ConnectionError, match="Connection closed"):
        await client.wait_for_daemon_ready(ready_timeout_s=0.5)


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


@pytest.mark.asyncio
async def test_wait_for_daemon_ready_skips_handshake_status_in_inbound_queue() -> None:
    """Handshake status must not block daemon_ready when using the background reader."""
    import asyncio

    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()
    handshake_status = {"type": "status", "state": "idle", "input_history": []}
    daemon_ready = {"type": "daemon_ready", "state": "ready"}
    client._read_from_socket = AsyncMock(  # type: ignore[method-assign]
        side_effect=[handshake_status, daemon_ready, None]
    )
    client._reader_task = asyncio.create_task(client._socket_reader_loop())
    await asyncio.sleep(0.05)

    result = await client.wait_for_daemon_ready(ready_timeout_s=1.0)
    assert result["state"] == "ready"
    assert len(client._pending_events) == 0

    await client.close()


def test_peel_stale_pending_control_events() -> None:
    """Handshake/RPC leftovers must not block turn progress detection."""
    client = WebSocketClient()
    client._pending_events.append({"type": "daemon_ready", "state": "ready"})
    client._pending_events.append(
        {"type": "loop_subscribe_response", "loop_id": "abc", "success": True}
    )
    client._pending_events.append({"type": "status", "state": "running", "loop_id": "abc"})

    removed = client.peel_stale_pending_control_events()

    assert removed == ["daemon_ready", "loop_subscribe_response"]
    assert len(client._pending_events) == 1
    assert client._pending_events[0]["type"] == "status"


@pytest.mark.asyncio
async def test_background_reader_delivers_events_to_read_event() -> None:
    """Socket reader task should feed read_event without blocking on UI work."""
    import asyncio

    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()
    payload = {"type": "status", "state": "running"}
    client._read_from_socket = AsyncMock(side_effect=[payload, None])  # type: ignore[method-assign]
    client._reader_task = asyncio.create_task(client._socket_reader_loop())

    first = await asyncio.wait_for(client.read_event(), timeout=1.0)
    assert first == payload

    await client.close()
