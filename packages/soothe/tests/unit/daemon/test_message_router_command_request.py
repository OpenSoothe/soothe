"""Tests for ``command_request`` routing through MessageRouter (RFC-404)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from soothe.daemon.message_router import MessageRouter


@pytest.mark.asyncio
async def test_command_request_enqueued_for_input_loop() -> None:
    """WebSocket ``command_request`` must reach the sequential input queue."""
    q: asyncio.Queue = asyncio.Queue()

    class _FakeDaemon:
        _current_input_queue = q

        async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
            raise AssertionError("_send_client_message should not run for command_request")

    router = MessageRouter(_FakeDaemon())
    req = {
        "type": "command_request",
        "command": "memory",
        "thread_id": "thread-1",
        "params": {},
        "request_id": "rid-cmd-404",
    }
    await router.dispatch("client-ws", req)

    queued = await asyncio.wait_for(q.get(), timeout=2.0)
    assert queued == req
    assert queued["type"] == "command_request"
    assert queued["request_id"] == "rid-cmd-404"
