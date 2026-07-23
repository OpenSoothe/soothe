"""Unit tests for daemon admin RPC helper (sdk wire only)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from soothe_sdk.wire.codec import MessageType

from soothe_daemon.admin_rpc import memory_stats, send_admin_request


class _FakeWs:
    """Minimal async WebSocket stub for handshake + one request/response."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._phase = 0

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self) -> str:
        if self._phase == 0:
            self._phase = 1
            return json.dumps(
                {
                    "type": "connection_ack",
                    "result": {"readiness_state": "ready", "protocol_version": "1"},
                }
            )
        req = json.loads(self.sent[-1])
        return json.dumps(
            {
                "type": MessageType.RESPONSE.value,
                "id": req["id"],
                "result": {"memory_stats": {"rss_mb": 1.5}},
            }
        )

    async def __aenter__(self) -> _FakeWs:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_send_admin_request_returns_result() -> None:
    ws = _FakeWs()

    with patch("websockets.connect", return_value=ws):
        result = await send_admin_request(
            "ws://127.0.0.1:9", "memory_stats", {"mode": "daemon"}, timeout=2.0
        )

    assert result == {"memory_stats": {"rss_mb": 1.5}}
    assert len(ws.sent) == 2


def test_memory_stats_sync_wrapper() -> None:
    with patch(
        "soothe_daemon.admin_rpc.send_admin_request",
        new_callable=AsyncMock,
        return_value={"memory_stats": {"rss_mb": 2.0}},
    ) as mock_send:
        out = memory_stats("ws://127.0.0.1:9", "daemon", timeout=5.0)
    assert out == {"memory_stats": {"rss_mb": 2.0}}
    mock_send.assert_awaited_once()
