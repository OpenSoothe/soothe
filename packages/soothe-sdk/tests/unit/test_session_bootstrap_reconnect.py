"""Tests for session bootstrap reconnection (protocol-1 flow, IG-522 Phase 7)."""

from __future__ import annotations

from typing import Any

import pytest

from soothe_sdk.client.session import bootstrap_loop_session


class _ReconnectClient:
    """Fake client that starts disconnected, supports protocol-1 methods."""

    def __init__(self) -> None:
        self.closed = False
        self.reconnected = False
        self._alive = False
        self.calls: list[tuple[str, Any]] = []

    def is_connection_alive(self) -> bool:
        return self._alive

    async def close(self) -> None:
        self.closed = True

    async def request_connection_init(self) -> None:
        self.calls.append(("request_connection_init", None))

    async def wait_for_connection_ack(self, *, ack_timeout_s: float) -> dict[str, Any]:
        self.calls.append(("wait_for_connection_ack", ack_timeout_s))
        return {
            "proto": "1",
            "type": "connection_ack",
            "result": {"readiness_state": "ready", "protocol_version": "1"},
        }

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        self.calls.append(("request", method, dict(params or {}), timeout))
        if method == "loop_new":
            return {"loop_id": "loop-reconnected"}
        if method == "loop_reattach":
            return {}
        msg = f"unexpected request method {method}"
        raise AssertionError(msg)

    async def subscribe(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 5.0,
    ) -> str:
        self.calls.append(("subscribe", method, dict(params or {}), timeout))
        return "sub-1"


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
    )

    assert client.closed is True
    assert connect_calls == [client]
    assert result.get("loop_id") == "loop-reconnected"

    # After reconnect, the full protocol-1 handshake is performed.
    assert ("request_connection_init", None) in client.calls
    assert any(c[0] == "wait_for_connection_ack" for c in client.calls)

    # loop_new via request()
    reqs = [c for c in client.calls if c[0] == "request"]
    assert len(reqs) == 1
    assert reqs[0][1] == "loop_new"

    # subscribe via subscribe()
    subs = [c for c in client.calls if c[0] == "subscribe"]
    assert len(subs) == 1
    assert subs[0][1] == "loop_events"


@pytest.mark.asyncio
async def test_bootstrap_reconnect_with_resume_uses_reattach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reconnect with a resume_loop_id triggers ``loop_reattach`` then ``subscribe``."""
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
        resume_loop_id="loop-resume",
    )

    assert client.closed is True
    assert connect_calls == [client]
    assert result.get("loop_id") == "loop-resume"

    # Should issue loop_reattach (not loop_new)
    reqs = [c for c in client.calls if c[0] == "request"]
    assert len(reqs) == 1
    assert reqs[0][1] == "loop_reattach"
    assert reqs[0][2].get("loop_id") == "loop-resume"

    # And subscribe to loop_events
    subs = [c for c in client.calls if c[0] == "subscribe"]
    assert len(subs) == 1
    assert subs[0][1] == "loop_events"
    assert subs[0][2].get("loop_id") == "loop-resume"


@pytest.mark.asyncio
async def test_bootstrap_no_reconnect_when_alive() -> None:
    """When the socket is alive, no reconnect occurs — straight to handshake."""
    client = _ReconnectClient()
    client._alive = True

    result = await bootstrap_loop_session(
        client,
        resume_loop_id=None,
    )

    assert client.closed is False
    assert result.get("loop_id") == "loop-reconnected"

    # Handshake still happens
    assert ("request_connection_init", None) in client.calls
