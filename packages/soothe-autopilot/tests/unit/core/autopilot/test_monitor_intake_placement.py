"""Async placement refine after fast goal intake."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe.config import SootheConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus

from soothe_autopilot.monitor import AutopilotMonitor
from soothe_autopilot.monitor.models import GoalPlacement


def _make_monitor(ce: ContextEngine | None = None) -> AutopilotMonitor:
    ce = ce or ContextEngine()
    bus = InternalEventBus()
    config = SootheConfig()
    with patch.object(SootheConfig, "create_chat_model", return_value=MagicMock()):
        return AutopilotMonitor(ce=ce, bus=bus, config=config)


@pytest.mark.asyncio
async def test_intake_returns_before_placement_llm() -> None:
    """intake_goal must not await placement; goal exists immediately."""
    monitor = _make_monitor()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_placement(_description: str) -> GoalPlacement:
        started.set()
        await release.wait()
        return GoalPlacement(adjusted_priority=80, suggested_dependencies=[], reasoning="ok")

    monitor._verifier.analyze_placement = slow_placement  # type: ignore[method-assign]

    result = await monitor.intake_goal("ship feature", priority=55)
    assert result.status == "accepted"
    assert result.goal_id
    goal = monitor._ce.get_goal_sync(result.goal_id)
    assert goal is not None
    assert goal.priority == 55
    assert goal.status == "pending"

    tasks = list(monitor._placement_tasks)
    assert len(tasks) == 1
    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert goal.priority == 55  # refine not applied yet
    release.set()
    await asyncio.wait_for(tasks[0], timeout=1.0)
    assert goal.priority == 80


@pytest.mark.asyncio
async def test_placement_refine_merges_deps_and_persists() -> None:
    ce = ContextEngine()
    upstream = await ce.create_goal("upstream")
    monitor = _make_monitor(ce)
    persist = AsyncMock()
    monitor.bind_dag_persist(persist)

    async def placement(_description: str) -> GoalPlacement:
        return GoalPlacement(
            adjusted_priority=66,
            suggested_dependencies=[upstream.id],
            suggested_informs=[upstream.id],
            reasoning="wire upstream",
        )

    monitor._verifier.analyze_placement = placement  # type: ignore[method-assign]
    result = await monitor.intake_goal("downstream", priority=40)
    assert result.goal_id
    tasks = list(monitor._placement_tasks)
    assert tasks
    await asyncio.wait_for(tasks[0], timeout=1.0)

    goal = ce.get_goal_sync(result.goal_id)
    assert goal is not None
    assert goal.priority == 66
    assert upstream.id in goal.depends_on
    assert upstream.id in goal.informs
    persist.assert_awaited()


@pytest.mark.asyncio
async def test_placement_refine_skips_non_pending() -> None:
    monitor = _make_monitor()

    async def placement(_description: str) -> GoalPlacement:
        return GoalPlacement(adjusted_priority=99, reasoning="late")

    monitor._verifier.analyze_placement = placement  # type: ignore[method-assign]
    result = await monitor.intake_goal("claim me", priority=50)
    assert result.goal_id
    claimed = monitor._ce.claim_goal(result.goal_id, loop_id="loop-1")
    assert claimed is not None
    assert claimed.status == "active"

    tasks = list(monitor._placement_tasks)
    assert tasks
    await asyncio.wait_for(tasks[0], timeout=1.0)
    assert claimed.priority == 50


@pytest.mark.asyncio
async def test_stop_cancels_in_flight_placement() -> None:
    monitor = _make_monitor()
    release = asyncio.Event()

    async def slow_placement(_description: str) -> GoalPlacement:
        await release.wait()
        return GoalPlacement(adjusted_priority=70)

    monitor._verifier.analyze_placement = slow_placement  # type: ignore[method-assign]
    await monitor.start()
    try:
        await monitor.intake_goal("hanging refine")
        assert monitor._placement_tasks
        await monitor.stop()
        assert not monitor._placement_tasks
    finally:
        release.set()
