"""Tests for soothe.internal broadcast suppression (IG-435)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_daemon.event import loop_event_topic
from soothe_daemon.event.bus import EventBus
from soothe_daemon.server import SootheDaemon


@pytest.mark.asyncio
async def test_broadcast_drops_internal_catalog_events() -> None:
    """Internal catalog types must not be published to the loop event bus."""
    bus = EventBus()
    published: list[tuple[str, dict]] = []

    async def capture_publish(topic: str, msg: dict, **kwargs: object) -> None:
        published.append((topic, msg))

    bus.publish = capture_publish  # type: ignore[method-assign]

    daemon = MagicMock(spec=SootheDaemon)
    daemon._event_bus = bus
    daemon._internal_events_suppressed = 0

    await SootheDaemon._broadcast(
        daemon,
        {
            "type": "event",
            "loop_id": "loop-1",
            "data": {"type": "soothe.internal.iteration.started", "iteration": 1},
        },
    )

    assert published == []
    assert daemon._internal_events_suppressed == 1


@pytest.mark.asyncio
async def test_broadcast_allows_client_catalog_events() -> None:
    """Client-facing cognition events are still published."""
    bus = EventBus()
    published: list[tuple[str, dict]] = []

    async def capture_publish(topic: str, msg: dict, **kwargs: object) -> None:
        published.append((topic, msg))

    bus.publish = capture_publish  # type: ignore[method-assign]

    daemon = MagicMock(spec=SootheDaemon)
    daemon._event_bus = bus
    daemon._internal_events_suppressed = 0
    daemon._session_manager = MagicMock()
    daemon._session_manager.wake_senders_for_loop = AsyncMock()

    msg = {
        "type": "event",
        "loop_id": "loop-1",
        "data": {"type": "soothe.cognition.agent_loop.started", "goal": "x"},
    }
    await SootheDaemon._broadcast(daemon, msg)

    assert len(published) == 1
    assert published[0][0] == loop_event_topic("loop-1")


@pytest.mark.asyncio
async def test_broadcast_drops_verbose_catalog_events() -> None:
    """DETAILED/DEBUG catalog events must not be published to client event bus."""
    bus = EventBus()
    published: list[tuple[str, dict]] = []

    async def capture_publish(topic: str, msg: dict, **kwargs: object) -> None:
        published.append((topic, msg))

    bus.publish = capture_publish  # type: ignore[method-assign]

    daemon = MagicMock(spec=SootheDaemon)
    daemon._event_bus = bus
    daemon._internal_events_suppressed = 0

    await SootheDaemon._broadcast(
        daemon,
        {
            "type": "event",
            "loop_id": "loop-1",
            "data": {"type": "soothe.lifecycle.loop.checkpoint_saved"},
        },
    )

    assert published == []
