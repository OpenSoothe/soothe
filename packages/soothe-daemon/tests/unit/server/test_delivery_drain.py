"""Tests for pre-idle session queue drain (goal_completion delivery)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from soothe_daemon.event import loop_event_topic
from soothe_daemon.event.bus import EventBus
from soothe_daemon.server.session import ClientSessionManager


@pytest.mark.asyncio
async def test_await_loop_delivery_drained_empty_queue() -> None:
    bus = EventBus()
    manager = ClientSessionManager(bus)
    loop_id = "loop-drain-1"
    queue: asyncio.Queue = asyncio.Queue()
    await bus.subscribe(loop_event_topic(loop_id), queue)

    session = MagicMock()
    session.event_queue = queue
    session.subscriptions = {loop_id}
    manager._sessions["client-1"] = session

    drained = await manager.await_loop_delivery_drained(
        loop_id,
        batch_timeout_s=0.05,
        max_wait_s=2.0,
    )
    assert drained is True


@pytest.mark.asyncio
async def test_await_loop_delivery_drained_waits_for_backlog() -> None:
    bus = EventBus()
    manager = ClientSessionManager(bus)
    loop_id = "loop-drain-2"
    queue: asyncio.Queue = asyncio.Queue()
    await bus.subscribe(loop_event_topic(loop_id), queue)
    await queue.put({"type": "status", "state": "running"})

    session = MagicMock()
    session.event_queue = queue
    session.subscriptions = {loop_id}
    manager._sessions["client-1"] = session

    async def _drain_later() -> None:
        await asyncio.sleep(0.15)
        while not queue.empty():
            queue.get_nowait()

    drain_task = asyncio.create_task(
        manager.await_loop_delivery_drained(
            loop_id,
            batch_timeout_s=0.05,
            max_wait_s=2.0,
        )
    )
    clear_task = asyncio.create_task(_drain_later())
    drained = await drain_task
    await clear_task
    assert drained is True
