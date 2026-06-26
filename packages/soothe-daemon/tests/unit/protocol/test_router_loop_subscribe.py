"""Tests for loop_subscribe decoupling from card replay."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe_daemon.protocol import MessageRouter


@pytest.mark.asyncio
async def test_loop_subscribe_responds_before_background_reattach() -> None:
    gate = asyncio.Event()
    sent: list[dict] = []

    async def _slow_reattach(_loop_id: str, _daemon: object, _client_id: str) -> None:
        await gate.wait()

    session_manager = MagicMock()
    session_manager.subscribe_loop = AsyncMock()
    session_manager.get_session = AsyncMock(return_value=SimpleNamespace())
    session_manager.send_to_client = AsyncMock()

    daemon = SimpleNamespace(
        _session_manager=session_manager,
        _persistence_manager=MagicMock(),
    )
    daemon._persistence_manager.get_loop_metadata = AsyncMock(return_value={"loop_id": "loop-1"})
    daemon._send_client_message = AsyncMock(side_effect=lambda _cid, frame: sent.append(frame))

    router = MessageRouter(daemon)
    router._ensure_loop_exists = AsyncMock(return_value=True)  # type: ignore[method-assign]

    with (
        patch(
            "soothe_daemon.runtime.loop_autopilot_mode.ensure_loop_autopilot_mode",
            new=AsyncMock(return_value="autopilot"),
        ),
        patch(
            "soothe_daemon.event.reattachment.handle_loop_reattach",
            new=AsyncMock(side_effect=_slow_reattach),
        ),
    ):
        await router._handle_loop_subscribe(
            "client-a",
            {"type": "loop_subscribe", "loop_id": "loop-1", "request_id": "req-1"},
        )

    assert sent[-1]["type"] == "loop_subscribe_response"
    assert sent[-1]["success"] is True
    assert not gate.is_set()

    gate.set()
    await asyncio.sleep(0.05)
