"""Unit tests for the SDK WebSocketClient handshake + heartbeat (RFC-450 §8, phase 3).

Covers:
- ``request_connection_init()`` sends a correctly structured envelope
- ``wait_for_connection_ack()`` returns on ``ready`` readiness_state
- ``wait_for_connection_ack()`` raises ``ConnectionError`` on ``incompatible``
- ``wait_for_connection_ack()`` raises ``RuntimeError`` on ``error``/``degraded``
- ``wait_for_connection_ack()`` retries on transitional states (``starting``, ``warming``)
- Heartbeat ping/pong round-trip: reader intercepts ping and responds with pong
- Heartbeat timeout: no pong within timeout → connection considered dead
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_sdk.client.websocket import WebSocketClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ack_msg(
    *,
    readiness_state: str = "ready",
    protocol_version: str = "1",
    capabilities: list[str] | None = None,
    heartbeat_interval_ms: int = 30000,
    server_version: str = "0.6.12",
) -> dict:
    return {
        "proto": "1",
        "type": "connection_ack",
        "result": {
            "server_version": server_version,
            "protocol_version": protocol_version,
            "capabilities": capabilities
            if capabilities is not None
            else ["streaming", "batch", "heartbeat"],
            "readiness_state": readiness_state,
            "heartbeat_interval_ms": heartbeat_interval_ms,
        },
    }


# ---------------------------------------------------------------------------
# request_connection_init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_connection_init_sends_correct_envelope() -> None:
    """request_connection_init sends a connection_init envelope with accept_proto ['1']."""
    from websockets.asyncio.connection import State

    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()
    client._ws.state = State.OPEN
    client._ws.send = AsyncMock()

    await client.request_connection_init()

    client._ws.send.assert_awaited_once()
    sent_text = client._ws.send.call_args[0][0]
    import json

    sent = json.loads(sent_text)
    assert sent["proto"] == "1"
    assert sent["type"] == "connection_init"
    assert "params" in sent
    params = sent["params"]
    assert "1" in params["accept_proto"]
    assert "streaming" in params["capabilities"]
    assert "batch" in params["capabilities"]


@pytest.mark.asyncio
async def test_request_connection_init_handles_closed_connection() -> None:
    """request_connection_init should not raise on ConnectionError."""
    client = WebSocketClient()
    client._connected = False

    # Should not raise
    await client.request_connection_init()


# ---------------------------------------------------------------------------
# wait_for_connection_ack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_connection_ack_returns_on_ready() -> None:
    """wait_for_connection_ack succeeds when readiness_state is 'ready'."""
    client = WebSocketClient()
    client._connected = True
    ack = _ack_msg(readiness_state="ready")
    client._pending_events.append(ack)

    result = await client.wait_for_connection_ack(ack_timeout_s=0.5)

    assert result["type"] == "connection_ack"
    assert result["result"]["readiness_state"] == "ready"
    assert client._handshake_complete is True
    assert client._protocol_version == "1"
    assert "streaming" in client._negotiated_capabilities


@pytest.mark.asyncio
async def test_wait_for_connection_ack_raises_on_incompatible() -> None:
    """wait_for_connection_ack raises ConnectionError on 'incompatible' state."""
    client = WebSocketClient()
    client._connected = True
    client._pending_events.append(_ack_msg(readiness_state="incompatible"))

    with pytest.raises(ConnectionError, match="incompatible"):
        await client.wait_for_connection_ack(ack_timeout_s=0.5)


@pytest.mark.asyncio
async def test_wait_for_connection_ack_raises_on_error_state() -> None:
    """wait_for_connection_ack raises RuntimeError on 'error' state."""
    client = WebSocketClient()
    client._connected = True
    client._pending_events.append(_ack_msg(readiness_state="error"))

    with pytest.raises(RuntimeError):
        await client.wait_for_connection_ack(ack_timeout_s=0.5)


@pytest.mark.asyncio
async def test_wait_for_connection_ack_raises_on_degraded_state() -> None:
    """wait_for_connection_ack raises RuntimeError on 'degraded' state."""
    client = WebSocketClient()
    client._connected = True
    client._pending_events.append(_ack_msg(readiness_state="degraded"))

    with pytest.raises(RuntimeError):
        await client.wait_for_connection_ack(ack_timeout_s=0.5)


@pytest.mark.asyncio
async def test_wait_for_connection_ack_retries_on_starting(monkeypatch) -> None:
    """wait_for_connection_ack should poll through transitional states."""
    client = WebSocketClient()
    client._connected = True

    events = [
        _ack_msg(readiness_state="starting"),
        _ack_msg(readiness_state="ready"),
    ]
    event_iter = iter(events)

    async def mock_read() -> dict | None:
        try:
            return next(event_iter)  # type: ignore[no-any-return]
        except StopIteration:
            return None

    client._read_inbound_event = mock_read  # type: ignore[method-assign]

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    result = await client.wait_for_connection_ack(ack_timeout_s=0.5)
    assert result["result"]["readiness_state"] == "ready"


@pytest.mark.asyncio
async def test_wait_for_connection_ack_raises_on_connection_closed() -> None:
    """wait_for_connection_ack surfaces a closed socket as ConnectionError."""
    client = WebSocketClient()
    client._connected = False

    with pytest.raises(ConnectionError, match="Connection closed"):
        await client.wait_for_connection_ack(ack_timeout_s=0.5)


@pytest.mark.asyncio
async def test_wait_for_connection_ack_stores_heartbeat_interval() -> None:
    """wait_for_connection_ack stores the heartbeat_interval_ms from the ack."""
    client = WebSocketClient()
    client._connected = True
    ack = _ack_msg(heartbeat_interval_ms=15000)
    client._pending_events.append(ack)

    await client.wait_for_connection_ack(ack_timeout_s=0.5)

    assert client._heartbeat_interval_ms == 15000


# ---------------------------------------------------------------------------
# Heartbeat ping/pong
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reader_intercepts_ping_and_responds_pong() -> None:
    """The socket reader loop intercepts ping frames and responds with pong."""
    from websockets.asyncio.connection import State

    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()
    client._ws.state = State.OPEN
    client._ws.send = AsyncMock()

    ping_frame = {"proto": "1", "type": "ping"}
    normal_frame = {"proto": "1", "type": "status", "state": "idle"}
    client._read_from_socket = AsyncMock(side_effect=[ping_frame, normal_frame, None])  # type: ignore[method-assign]
    client._reader_task = asyncio.create_task(client._socket_reader_loop())

    # Wait for the reader to process frames
    first = await asyncio.wait_for(client.read_event(), timeout=1.0)
    assert first["type"] == "status"

    # Verify pong was sent in response to ping
    client._ws.send.assert_awaited()
    sent_text = client._ws.send.call_args[0][0]
    import json

    sent = json.loads(sent_text)
    assert sent["type"] == "pong"
    assert sent["proto"] == "1"

    await client.close()


@pytest.mark.asyncio
async def test_reader_intercepts_pong_without_error() -> None:
    """The socket reader loop silently consumes pong frames."""
    from websockets.asyncio.connection import State

    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()
    client._ws.state = State.OPEN

    pong_frame = {"proto": "1", "type": "pong"}
    normal_frame = {"proto": "1", "type": "status", "state": "idle"}
    client._read_from_socket = AsyncMock(side_effect=[pong_frame, normal_frame, None])  # type: ignore[method-assign]
    client._reader_task = asyncio.create_task(client._socket_reader_loop())

    first = await asyncio.wait_for(client.read_event(), timeout=1.0)
    assert first["type"] == "status"  # pong was consumed, not queued

    await client.close()


@pytest.mark.asyncio
async def test_heartbeat_timeout_closes_connection() -> None:
    """If no pong arrives within timeout, the connection is considered dead."""
    from websockets.asyncio.connection import State

    client = WebSocketClient()
    client._connected = True
    client._ws = MagicMock()
    client._ws.state = State.OPEN
    client._ws.send = AsyncMock()

    # Simulate a heartbeat timeout: the _handle_pong is never called,
    # so _last_pong_monotonic stays stale.
    import time

    client._last_pong_monotonic = time.monotonic() - 100  # 100s ago, way past timeout
    client._heartbeat_interval_ms = 100  # 100ms interval
    client._handshake_complete = True  # Start heartbeat

    # Start heartbeat with a very short timeout
    client._heartbeat_timeout_ms = 50
    client._start_heartbeat()

    # Wait a bit for the heartbeat loop to detect the timeout
    await asyncio.sleep(0.15)

    # The heartbeat task should have closed the connection
    assert client._connected is False

    # Clean up
    hb_task = client._heartbeat_task
    if hb_task is not None and not hb_task.done():
        hb_task.cancel()
        with contextlib_suppress():
            await hb_task


def contextlib_suppress():
    import contextlib

    return contextlib.suppress(asyncio.CancelledError, Exception)
