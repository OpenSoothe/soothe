"""Tests for TUI daemon session reconnect after connection loss."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe_cli.runtime.transport.session import TuiDaemonSession


class _AliveToggleClient:
    def __init__(self) -> None:
        self._alive = True
        self.closed = False

    def is_connection_alive(self) -> bool:
        return self._alive

    async def close(self) -> None:
        self.closed = True
        self._alive = False


@pytest.mark.asyncio
async def test_ensure_connected_noop_when_socket_open() -> None:
    """ensure_connected should not reconnect when the WebSocket is still open."""
    session = TuiDaemonSession.__new__(TuiDaemonSession)
    client = _AliveToggleClient()
    session._client = client  # noqa: SLF001
    session._rpc_client = MagicMock()
    session._rpc_connected = False
    session._loop_id = "loop-abc"
    session._bootstrap_loop = AsyncMock()

    await session.ensure_connected()

    session._bootstrap_loop.assert_not_awaited()
    assert client.closed is False


@pytest.mark.asyncio
async def test_ensure_connected_reconnects_and_resumes_loop() -> None:
    """ensure_connected should reconnect and re-subscribe to the active loop."""
    session = TuiDaemonSession.__new__(TuiDaemonSession)
    client = _AliveToggleClient()
    client._alive = False
    session._client = client  # noqa: SLF001
    session._rpc_client = MagicMock()
    session._rpc_client.close = AsyncMock()
    session._rpc_connected = True
    session._loop_id = "loop-resume-1"
    session._bootstrap_loop = AsyncMock(
        return_value={"type": "session_ready", "loop_id": "loop-resume-1"}
    )

    with patch(
        "soothe_cli.runtime.transport.session.connect_websocket_with_retries",
        new_callable=AsyncMock,
    ) as connect_mock:
        await session.ensure_connected()

    connect_mock.assert_awaited_once_with(client)
    assert client.closed is True
    session._bootstrap_loop.assert_awaited_once_with(resume_loop_id="loop-resume-1")


@pytest.mark.asyncio
async def test_iter_turn_chunks_raises_when_connection_drops_mid_query() -> None:
    """A dead socket after query start should surface as ConnectionError, not silent EOF."""
    events = [
        {"type": "status", "state": "running", "loop_id": "loop-1"},
    ]

    class _ReadClient:
        def __init__(self) -> None:
            self._events = list(events)

        def is_connection_alive(self) -> bool:
            return False

        def peel_stale_pending_control_events(self) -> list[str]:
            return []

        async def read_event(self) -> dict[str, Any] | None:
            if self._events:
                return self._events.pop(0)
            return None

    session = TuiDaemonSession.__new__(TuiDaemonSession)
    session._client = _ReadClient()  # noqa: SLF001
    session._loop_id = "loop-1"
    session._read_lock = asyncio.Lock()
    session.turn_event_stats = MagicMock()

    with pytest.raises(ConnectionError, match="Daemon connection lost"):
        async for _chunk in session.iter_turn_chunks():
            pass


@pytest.mark.asyncio
async def test_detach_skips_when_not_connected() -> None:
    """detach should not raise when the stream socket is already closed."""
    session = TuiDaemonSession.__new__(TuiDaemonSession)
    client = MagicMock()
    client.is_connected = False
    client.notify = AsyncMock()
    session._client = client  # noqa: SLF001

    await session.detach()

    client.notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_detach_swallows_connection_error_from_notify() -> None:
    """detach should tolerate a race where the socket dies before notify."""
    session = TuiDaemonSession.__new__(TuiDaemonSession)
    client = MagicMock()
    client.is_connected = True
    client.notify = AsyncMock(side_effect=ConnectionError("Connection closed"))
    session._client = client  # noqa: SLF001

    await session.detach()

    client.notify.assert_awaited_once_with("disconnect", {})
