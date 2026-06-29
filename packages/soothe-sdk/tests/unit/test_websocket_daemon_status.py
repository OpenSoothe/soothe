"""Tests for coalesced ``daemon_status`` fetches on ``WebSocketClient``."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from soothe_sdk.client.websocket import WebSocketClient


@pytest.mark.asyncio
async def test_fetch_daemon_status_coalesces_concurrent_callers() -> None:
    """Many overlapping waits must share a single ``request`` call."""
    client = WebSocketClient(url="ws://127.0.0.1:9")
    calls = 0

    async def slow_request(
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 5.0,
        proto: str = "1",
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        assert method == "daemon_status"
        await asyncio.sleep(0.02)
        return {"running": True}

    client.request = AsyncMock(side_effect=slow_request)  # type: ignore[method-assign]

    r1, r2, r3 = await asyncio.gather(
        client.fetch_daemon_status(min_interval_s=1.0),
        client.fetch_daemon_status(min_interval_s=1.0),
        client.fetch_daemon_status(min_interval_s=1.0),
    )
    assert calls == 1
    assert r1 == r2 == r3


@pytest.mark.asyncio
async def test_fetch_daemon_status_ttl_avoids_extra_rpc() -> None:
    """Sequential calls inside the TTL window must not send again."""
    client = WebSocketClient(url="ws://127.0.0.1:9")
    mock_request = AsyncMock(
        return_value={"running": True},
    )
    client.request = mock_request  # type: ignore[method-assign]

    await client.fetch_daemon_status(min_interval_s=10.0)
    await client.fetch_daemon_status(min_interval_s=10.0)
    assert mock_request.await_count == 1


@pytest.mark.asyncio
async def test_fetch_daemon_status_min_interval_zero_always_rpc() -> None:
    """``min_interval_s=0`` disables cache."""
    client = WebSocketClient(url="ws://127.0.0.1:9")
    mock_request = AsyncMock(
        return_value={"running": True},
    )
    client.request = mock_request  # type: ignore[method-assign]

    await client.fetch_daemon_status(min_interval_s=0)
    await client.fetch_daemon_status(min_interval_s=0)
    assert mock_request.await_count == 2
