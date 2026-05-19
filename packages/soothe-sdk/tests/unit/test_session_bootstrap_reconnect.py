"""Tests for session bootstrap reconnection."""

from __future__ import annotations

from typing import Any

import pytest

from soothe_sdk.client.session import bootstrap_loop_session


class _ReconnectClient:
    def __init__(self) -> None:
        self.closed = False
        self.reconnected = False
        self._alive = False

    def is_connection_alive(self) -> bool:
        return self._alive

    async def close(self) -> None:
        self.closed = True

    async def request_daemon_ready(self) -> None:
        pass

    async def wait_for_daemon_ready(self, *, ready_timeout_s: float) -> dict[str, Any]:
        return {"type": "daemon_ready", "state": "ready"}

    async def request_response(
        self,
        payload: dict[str, Any],
        *,
        response_type: str,
        timeout: float,
    ) -> dict[str, Any]:
        if payload.get("type") == "loop_new":
            return {"type": "loop_new_response", "loop_id": "loop-reconnected"}
        return {"type": "loop_subscribe_response", "success": True}


@pytest.mark.asyncio
async def test_bootstrap_reconnects_when_socket_not_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """bootstrap_loop_session should reconnect before handshake when the socket died."""
    client = _ReconnectClient()
    connect_calls: list[Any] = []

    async def _fake_connect(c: Any) -> None:
        connect_calls.append(c)
        c._alive = True

    monkeypatch.setattr(
        "soothe_sdk.client.session.connect_websocket_with_retries",
        _fake_connect,
    )

    result = await bootstrap_loop_session(
        client,
        resume_loop_id=None,
        verbosity="normal",
    )

    assert client.closed is True
    assert connect_calls == [client]
    assert result.get("loop_id") == "loop-reconnected"
