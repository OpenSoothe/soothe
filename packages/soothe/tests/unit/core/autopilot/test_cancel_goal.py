"""Tests for AutopilotService.cancel_goal worker propagation (RFC-222 H8)."""

from __future__ import annotations

import pytest

from soothe.config.models import AutonomousConfig
from soothe.core.autopilot import AutopilotService
from soothe.core.events.internal_bus import InternalEventBus
from soothe.core.goal_engine import GoalEngine


class _FakeRunner:
    def __init__(self, loop_id: str) -> None:
        self.loop_id = loop_id
        self.cancel_called = False

    async def run(self, request):  # noqa: ANN001
        yield None

    async def cancel(self) -> None:
        self.cancel_called = True


class _FakeFactory:
    def create_runner(self, loop_id: str):  # noqa: ANN001
        return _FakeRunner(loop_id)


def _service() -> AutopilotService:
    bus = InternalEventBus()
    ge = GoalEngine(internal_bus=bus)
    cfg = AutonomousConfig(max_loops=2, max_parallel_goals=2)
    return AutopilotService(
        goal_engine=ge,
        config=cfg,
        internal_bus=bus,
        runner_factory=_FakeFactory(),
    )


class TestCancelGoal:
    @pytest.mark.asyncio
    async def test_unknown_goal_returns_none(self) -> None:
        svc = _service()
        result = await svc.cancel_goal("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_pending_goal_no_worker_just_fails(self) -> None:
        svc = _service()
        goal = await svc.submit_task("g", max_retries=0)
        result = await svc.cancel_goal(goal.id, reason="user_quit")
        assert result is not None
        assert result.status == "failed"
        # No worker assigned, so nothing to cancel.

    @pytest.mark.asyncio
    async def test_active_goal_cancels_worker_and_fails(self) -> None:
        svc = _service()
        goal = await svc.submit_task("g", max_retries=0)
        worker = await svc._worker_pool.pick_worker(goal)
        assert worker is not None
        # Mark goal active on this worker.
        await svc._goal_engine.claim_goal(goal.id, loop_id=worker.loop_id)

        result = await svc.cancel_goal(goal.id, reason="user_cancelled")

        assert worker.runner.cancel_called is True
        assert result is not None
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_cancel_no_retry_even_if_retries_left(self) -> None:
        """allow_retry=False short-circuits the retry path."""
        svc = _service()
        # max_retries default would normally let it retry; cancel should override.
        goal = await svc.submit_task("g", max_retries=5)
        worker = await svc._worker_pool.pick_worker(goal)
        assert worker is not None
        await svc._goal_engine.claim_goal(goal.id, loop_id=worker.loop_id)

        result = await svc.cancel_goal(goal.id)

        assert result is not None
        assert result.status == "failed"  # not pending — no retry
