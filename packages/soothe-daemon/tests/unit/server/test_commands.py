"""Tests for ``command_request`` routing through MessageRouter (RFC-454)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from soothe_daemon.protocol import MessageRouter


@pytest.mark.asyncio
async def test_command_request_enqueued_for_loop_dispatcher() -> None:
    """WebSocket ``command_request`` must reach the per-loop input dispatcher."""
    q: asyncio.Queue = asyncio.Queue()

    async def enqueue(loop_id: str, msg: dict[str, Any]) -> None:
        await q.put((loop_id, msg))

    loop_id = "loop-r"

    class _FakeDaemon:
        _loop_input_dispatcher = SimpleNamespace(enqueue=enqueue)
        _session_manager = SimpleNamespace(
            get_session=AsyncMock(return_value=SimpleNamespace(subscriptions={loop_id}))
        )

        async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
            raise AssertionError("_send_client_message should not run for command_request")

    router = MessageRouter(_FakeDaemon())
    req = {
        "type": "command_request",
        "command": "memory",
        "params": {},
        "request_id": "rid-cmd-404",
    }
    await router.dispatch("client-ws", req)

    got_loop, queued = await asyncio.wait_for(q.get(), timeout=2.0)
    assert got_loop == loop_id
    assert queued["type"] == "command_request"
    assert queued["request_id"] == "rid-cmd-404"
    assert queued["client_id"] == "client-ws"
