"""Tests for async loop reattachment scheduling."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from soothe_daemon.event.reattachment import schedule_loop_reattach


@pytest.mark.asyncio
async def test_schedule_loop_reattach_runs_in_background() -> None:
    daemon = object()
    client_id = "client-1"
    loop_id = "loop-12345678"
    gate = asyncio.Event()

    async def _fake_handle(loop: str, _daemon: object, _client: str) -> None:
        assert loop == loop_id
        gate.set()

    with patch(
        "soothe_daemon.event.reattachment.handle_loop_reattach",
        new=AsyncMock(side_effect=_fake_handle),
    ):
        task = schedule_loop_reattach(loop_id, daemon, client_id)
        assert not gate.is_set()
        await asyncio.wait_for(gate.wait(), timeout=1.0)
        await task
