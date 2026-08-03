"""Tests for AutopilotService H5 deadline enforcement (RFC-222 revised, RFC-625)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from soothe.autopilot import AutopilotService
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus


class _FakeRunner:
    def __init__(self, loop_id: str) -> None:
        self.loop_id = loop_id
        self.cancel_called = False

    async def run(self, request):  # noqa: ANN001
        yield None  # never reached in monitor-only tests

    async def cancel(self) -> None:
        self.cancel_called = True


class _FakeFactory:
    def create_runner(self, loop_id: str):  # noqa: ANN001
        return _FakeRunner(loop_id)


def _service(*, deadline: float | None) -> AutopilotService:
    bus = InternalEventBus()
    ce = ContextEngine()
    cfg = AutopilotConfig(max_loops=2, max_parallel_goals=2)
    cfg.goal_deadline_seconds = deadline
    return AutopilotService(
        ce=ce,
        config=cfg,
        internal_bus=bus,
        runner_factory=_FakeFactory(),
    )


class TestDeadlineMonitorNoOps:
    @pytest.mark.asyncio
    async def test_no_deadline_configured_skips(self) -> None:
        svc = _service(deadline=None)
        # Manually claim a worker far in the past — no deadline so no action.
        goal = await svc.submit_task("g1", max_retries=0)
        worker = await svc._worker_pool.pick_worker(goal, job_id=goal.id)
        assert worker is not None
        worker.dispatch_started_at = datetime.now(UTC) - timedelta(seconds=600)
        await svc._monitor_loop_health()
        assert worker.runner.cancel_called is False

    @pytest.mark.asyncio
    async def test_under_deadline_skips(self) -> None:
        svc = _service(deadline=60.0)
        goal = await svc.submit_task("g1", max_retries=0)
        worker = await svc._worker_pool.pick_worker(goal, job_id=goal.id)
        assert worker is not None
        svc._ce.claim_goal(goal.id, loop_id=worker.loop_id)
        # Just started — well under deadline.
        await svc._monitor_loop_health()
        assert worker.runner.cancel_called is False
        refreshed = await svc.get_goal(goal.id)
        assert refreshed.status == "active"


class TestDeadlineMonitorEnforces:
    @pytest.mark.asyncio
    async def test_overrun_cancels_worker_and_fails_goal(self) -> None:
        svc = _service(deadline=1.0)
        goal = await svc.submit_task("slow", max_retries=0)
        worker = await svc._worker_pool.pick_worker(goal, job_id=goal.id)
        assert worker is not None
        svc._ce.claim_goal(goal.id, loop_id=worker.loop_id)
        # Pretend the worker started long enough ago to overrun.
        worker.dispatch_started_at = datetime.now(UTC) - timedelta(seconds=10)

        await svc._monitor_loop_health()

        assert worker.runner.cancel_called is True
        finished = await svc.get_goal(goal.id)
        assert finished is not None
        assert finished.status == "failed"

    @pytest.mark.asyncio
    async def test_no_started_at_skips(self) -> None:
        svc = _service(deadline=1.0)
        goal = await svc.submit_task("g1", max_retries=0)
        worker = await svc._worker_pool.pick_worker(goal, job_id=goal.id)
        assert worker is not None
        worker.dispatch_started_at = None  # idle-ish
        await svc._monitor_loop_health()
        assert worker.runner.cancel_called is False
