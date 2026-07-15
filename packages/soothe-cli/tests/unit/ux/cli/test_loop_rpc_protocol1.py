"""Tests for the protocol-1 ``_rpc`` helper in loop_cmd (RFC-450 clean cut).

``_rpc`` now takes ``(ws_url, method, params, mode=...)`` and calls the
protocol-1 ``WebSocketClient.request()`` / ``notify()`` / ``subscribe()``
API directly. These tests stub the client and assert the helper translates
``ProtocolError`` / ``TimeoutError`` into the ``{"error": ...}`` dict
contract used by command handlers.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from soothe_cli.cli.commands import loop_cmd


class _FakeClient:
    """Minimal WebSocketClient stub that records protocol-1 calls."""

    def __init__(
        self,
        *,
        result: Any = None,
        exc: Exception | None = None,
        sub_id: str | None = None,
    ) -> None:
        self._result = result
        self._exc = exc
        self._sub_id = sub_id
        self.request_calls: list[tuple[str, dict[str, Any]]] = []
        self.notify_calls: list[tuple[str, dict[str, Any]]] = []
        self.subscribe_calls: list[tuple[str, dict[str, Any]]] = []
        self.connection_init_calls = 0
        self.connection_ack_calls: list[float] = []

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def request_connection_init(self) -> None:
        self.connection_init_calls += 1

    async def wait_for_connection_ack(self, ack_timeout_s: float = 10.0) -> dict[str, Any]:
        self.connection_ack_calls.append(ack_timeout_s)
        return {
            "type": "connection_ack",
            "result": {
                "readiness_state": "ready",
                "protocol_version": "1",
                "capabilities": ["streaming", "batch", "heartbeat"],
            },
        }

    async def request(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 5.0
    ) -> dict[str, Any]:
        self.request_calls.append((method, params or {}))
        if self._exc:
            raise self._exc
        return self._result  # type: ignore[return-value]

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self.notify_calls.append((method, params or {}))
        if self._exc:
            raise self._exc

    async def subscribe(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 5.0,
    ) -> str:
        self.subscribe_calls.append((method, params or {}))
        if self._exc:
            raise self._exc
        return self._sub_id or "sub-123"


def _make_patch(fake: _FakeClient) -> Any:
    """Return a patch context that replaces WebSocketClient with ``fake``."""
    return patch("soothe_cli.cli.commands.loop_cmd.WebSocketClient", return_value=fake)


@pytest.mark.asyncio
async def test_rpc_request_returns_result_dict_directly() -> None:
    """_rpc in request mode calls request() and returns the result dict."""
    fake = _FakeClient(result={"loops": [{"loop_id": "abc", "status": "running"}]})
    with _make_patch(fake):
        response = await loop_cmd._rpc("ws://test", "loop_list", {"limit": 20})
    assert response == {"loops": [{"loop_id": "abc", "status": "running"}]}
    assert fake.request_calls[0] == ("loop_list", {"limit": 20})
    assert not fake.notify_calls
    assert fake.connection_init_calls == 1
    assert fake.connection_ack_calls == [30.0]


@pytest.mark.asyncio
async def test_rpc_notify_returns_empty_dict() -> None:
    """_rpc in notify mode calls notify() and returns {}."""
    fake = _FakeClient()
    with _make_patch(fake):
        response = await loop_cmd._rpc(
            "ws://test", "loop_input", {"loop_id": "loop_1", "content": "hi"}, mode="notify"
        )
    assert response == {}
    assert "error" not in response
    assert fake.notify_calls[0] == ("loop_input", {"loop_id": "loop_1", "content": "hi"})
    assert not fake.request_calls
    assert fake.connection_init_calls == 1


@pytest.mark.asyncio
async def test_rpc_subscribe_returns_subscription_id() -> None:
    """_rpc in subscribe mode calls subscribe() and wraps the id in a dict."""
    fake = _FakeClient(sub_id="sub-456")
    with _make_patch(fake):
        response = await loop_cmd._rpc(
            "ws://test", "loop_events", {"loop_id": "loop_1"}, mode="subscribe"
        )
    assert response == {"subscription_id": "sub-456"}
    assert "error" not in response
    assert fake.subscribe_calls[0] == ("loop_events", {"loop_id": "loop_1"})


@pytest.mark.asyncio
async def test_rpc_translates_protocol_error_to_error_dict() -> None:
    """_rpc catches ProtocolError and returns {"error": ...}."""
    from soothe_sdk.wire.codec import ProtocolError

    fake = _FakeClient(exc=ProtocolError(code=-32200, message="Loop not found"))
    with _make_patch(fake):
        response = await loop_cmd._rpc(
            "ws://test", "loop_get", {"loop_id": "missing", "verbose": False}
        )
    assert "error" in response
    assert "Loop not found" in response["error"]


@pytest.mark.asyncio
async def test_rpc_translates_timeout_to_error_dict() -> None:
    """_rpc catches TimeoutError and returns {"error": ...}."""
    fake = _FakeClient(exc=TimeoutError("timed out"))
    with _make_patch(fake):
        response = await loop_cmd._rpc(
            "ws://test",
            "loop_get",
            {"loop_id": "loop_1", "verbose": False},
            timeout=1.0,
        )
    assert response == {"error": "Timed out waiting for daemon response"}


@pytest.mark.asyncio
async def test_rpc_translates_connection_error_to_error_dict() -> None:
    """_rpc catches ConnectionError and returns {"error": ...}."""
    fake = _FakeClient(exc=ConnectionError("refused"))
    with _make_patch(fake):
        response = await loop_cmd._rpc("ws://test", "loop_list", {"limit": 20})
    assert "error" in response
    assert "Connection error" in response["error"]


@pytest.mark.asyncio
async def test_rpc_prune_result_fields_at_top_level() -> None:
    """Prune result fields are accessed directly (protocol-1 returns result dict)."""
    fake = _FakeClient(result={"pruned": 3, "remaining": 7, "dry_run": False})
    with _make_patch(fake):
        response = await loop_cmd._rpc(
            "ws://test",
            "loop_prune",
            {"loop_id": "loop_1", "retention_days": 30, "dry_run": False},
        )
    # The pruned/remaining fields are at the top level, not under "result".
    assert response.get("pruned") == 3
    assert response.get("remaining") == 7
    # The old "result" wrapper key must NOT be present.
    assert "result" not in response
