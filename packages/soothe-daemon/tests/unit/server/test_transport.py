"""Tests for soothe.internal broadcast suppression (IG-435)."""

from __future__ import annotations

import logging
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
        "data": {"type": "soothe.cognition.strange_loop.started", "goal": "x"},
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


@pytest.mark.asyncio
async def test_broadcast_publishes_messages_mode_envelope() -> None:
    """``mode=messages`` envelopes carry user-visible LangGraph payloads.

    Regression guard for loop ``…81ec`` (synthesis text and ledger-direct
    replays were silently dropped because the visibility filter did not
    enumerate this envelope shape).
    """
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
        "namespace": [],
        "mode": "messages",
        "data": [
            {
                "type": "AIMessageChunk",
                "content": "Final synthesis text...",
                "phase": "goal_completion",
            },
            {},
        ],
    }
    await SootheDaemon._broadcast(daemon, msg)

    assert len(published) == 1, "messages-mode envelope must reach the event bus"
    assert published[0][0] == loop_event_topic("loop-1")
    assert daemon._internal_events_suppressed == 0


@pytest.mark.asyncio
async def test_broadcast_suppression_log_includes_kind_and_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The first suppression in a window logs ``kind=`` and ``reason=`` for debuggability."""
    bus = EventBus()

    async def noop_publish(topic: str, msg: dict, **kwargs: object) -> None:
        return None

    bus.publish = noop_publish  # type: ignore[method-assign]

    daemon = MagicMock(spec=SootheDaemon)
    daemon._event_bus = bus
    # Start at 0 so the next suppression hits the ``% 500 == 1`` log boundary.
    daemon._internal_events_suppressed = 0

    with caplog.at_level(logging.DEBUG, logger="soothe_daemon.server"):
        await SootheDaemon._broadcast(
            daemon,
            {
                "type": "event",
                "loop_id": "loop-1",
                "mode": "custom",
                "data": {"type": "soothe.internal.iteration.started", "iteration": 1},
            },
        )

    matching = [
        r for r in caplog.records if "Suppressing non-client-visible event broadcast" in r.message
    ]
    assert matching, "expected suppression log to be emitted"
    formatted = matching[0].getMessage()
    assert "kind=event_catalog" in formatted, formatted
    assert "reason=catalog:soothe.internal.iteration.started:suppressed" in formatted, formatted
