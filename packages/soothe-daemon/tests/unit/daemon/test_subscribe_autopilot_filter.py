"""Tests that subscribe_loop refuses autopilot worker loop_ids (RFC-222)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe_daemon.event import EventBus
from soothe_daemon.session import ClientSessionManager


@pytest.mark.asyncio
async def test_subscribe_rejects_autopilot_worker_loop_id() -> None:
    bus = EventBus()
    manager = ClientSessionManager(bus)
    transport = MagicMock()
    transport.transport_type = "test"
    client_id = await manager.create_session(transport, None)

    # autopilot__wNNN is the WorkerPool-owned namespace.
    result = await manager.subscribe_loop(client_id, "autopilot__w001")

    assert result is False
    session = await manager.get_session(client_id)
    assert session is not None
    assert "autopilot__w001" not in session.subscriptions

    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_subscribe_allows_normal_loop_ids() -> None:
    bus = EventBus()
    manager = ClientSessionManager(bus)
    transport = MagicMock()
    transport.transport_type = "test"
    client_id = await manager.create_session(transport, None)

    result = await manager.subscribe_loop(client_id, "user-loop-123")

    assert result is True
    session = await manager.get_session(client_id)
    assert session is not None
    assert "user-loop-123" in session.subscriptions

    await manager.remove_session(client_id)


@pytest.mark.asyncio
async def test_subscribe_rejects_any_autopilot_prefix_variant() -> None:
    bus = EventBus()
    manager = ClientSessionManager(bus)
    transport = MagicMock()
    transport.transport_type = "test"
    client_id = await manager.create_session(transport, None)

    for bad in ("autopilot__w999", "autopilot__w042"):
        assert await manager.subscribe_loop(client_id, bad) is False

    await manager.remove_session(client_id)
