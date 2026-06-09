"""Tests for AutopilotService.cancel_goal worker propagation (RFC-222 H8)."""

from __future__ import annotations

import pytest

from soothe.config.models import AutonomousConfig
from soothe.foundation.autopilot.service import AutopilotService
from soothe.foundation.events.internal_bus import InternalEventBus
from soothe.foundation.autopilot.engine import GoalEngine


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
    async def test_pending_goal_no_worker_transitions_to_cancelled(self) -> None:
        svc = _service()
        goal = await svc.submit_task("g", max_retries=0)
        result = await svc.cancel_goal(goal.id, reason="user_quit")
        assert result is not None
        assert result.status == "cancelled"
        # No worker assigned, so nothing to cancel.

    @pytest.mark.asyncio
    async def test_active_goal_cancels_worker_and_transitions_to_cancelled(self) -> None:
        svc = _service()
        goal = await svc.submit_task("g", max_retries=0)
        worker = await svc._worker_pool.pick_worker(goal)
        assert worker is not None
        # Mark goal active on this worker.
        await svc._goal_engine.claim_goal(goal.id, loop_id=worker.loop_id)

        result = await svc.cancel_goal(goal.id, reason="user_cancelled")

        assert worker.runner.cancel_called is True
        assert result is not None
        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_no_retry_even_if_retries_left(self) -> None:
        """Cancellation is terminal regardless of retry budget."""
        svc = _service()
        goal = await svc.submit_task("g", max_retries=5)
        worker = await svc._worker_pool.pick_worker(goal)
        assert worker is not None
        await svc._goal_engine.claim_goal(goal.id, loop_id=worker.loop_id)

        result = await svc.cancel_goal(goal.id)

        assert result is not None
        assert result.status == "cancelled"
