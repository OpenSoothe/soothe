"""Tests for pre-idle session queue drain (goal_completion delivery)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.asyncio
async def test_await_loop_delivery_drained_waits_for_delivery_ack() -> None:
    """IG-556 P1.3: drain gates on client delivery_ack for terminal frames."""
    bus = EventBus()
    manager = ClientSessionManager(bus)
    loop_id = "loop-ack-1"
    transport = MagicMock()
    transport.name = "test"
    transport.send = AsyncMock()

    client_id = await manager.create_session(transport, None)
    await manager.subscribe_loop(client_id, loop_id)
    manager.note_delivery_sent(loop_id, client_id)

    async def _ack_later() -> None:
        await asyncio.sleep(0.08)
        manager.record_delivery_ack(client_id, loop_id, 1)

    ack_task = asyncio.create_task(_ack_later())
    drained = await manager.await_loop_delivery_drained(
        loop_id,
        batch_timeout_s=0.05,
        max_wait_s=2.0,
    )
    await ack_task
    assert drained is True

    await manager.remove_session(client_id)
