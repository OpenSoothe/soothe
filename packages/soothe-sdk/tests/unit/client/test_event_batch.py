"""Tests for WebSocket event_batch expansion (IG-435)."""

from __future__ import annotations

import asyncio

import pytest

from soothe_sdk.client.websocket import WebSocketClient


@pytest.mark.asyncio
async def test_enqueue_inbound_expands_event_batch() -> None:
    client = WebSocketClient("ws://127.0.0.1:9")
    await client._enqueue_inbound(
        {
            "type": "event_batch",
            "events": [{"type": "status", "state": "idle"}, {"type": "status", "state": "running"}],
        }
    )
    first = await asyncio.wait_for(client._inbound_queue.get(), timeout=1.0)
    second = await asyncio.wait_for(client._inbound_queue.get(), timeout=1.0)
    assert first == {"type": "status", "state": "idle"}
    assert second == {"type": "status", "state": "running"}
