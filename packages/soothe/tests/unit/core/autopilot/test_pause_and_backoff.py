"""Tests for AutopilotService.pause_job cascade (IG-678 P1-1)."""

from __future__ import annotations

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
        yield None

    async def cancel(self) -> None:
        self.cancel_called = True


class _FakeFactory:
    def create_runner(self, loop_id: str):  # noqa: ANN001
        return _FakeRunner(loop_id)


def _service() -> AutopilotService:
    return AutopilotService(
        ce=ContextEngine(),
        config=AutopilotConfig(max_loops=2, max_parallel_goals=2),
        internal_bus=InternalEventBus(),
        runner_factory=_FakeFactory(),
    )


@pytest.mark.asyncio
async def test_pause_job_suspends_children_and_cancels_worker() -> None:
    svc = _service()
    root = await svc.submit_task("root job")
    child = await svc._ce.create_goal("child work", parent_id=root.id)

    # Simulate an active child with an assigned worker.
    worker = await svc._worker_pool.pick_worker(child, job_id=root.id)
    assert worker is not None
    claimed = svc._ce.claim_goal(child.id, loop_id=worker.loop_id)
    assert claimed is not None
    assert claimed.status == "active"

    paused = await svc.pause_job(root.id, reason="user_pause")
    assert paused is not None
    assert paused.status == "suspended"

    child_after = await svc._ce.get_goal(child.id)
    assert child_after is not None
    assert child_after.status == "suspended"
    assert worker.runner.cancel_called is True


@pytest.mark.asyncio
async def test_retry_failed_goal_then_exhaust() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("flaky", max_retries=1)
    await ce.fail_goal(goal.id, error="boom")

    retried = await ce.retry_failed_goal(goal.id, reason="backoff")
    assert retried.status == "pending"
    assert retried.retry_count == 1

    await ce.fail_goal(goal.id, error="boom again")
    with pytest.raises(ValueError, match="exhausted"):
        await ce.retry_failed_goal(goal.id, reason="no more")


@pytest.mark.asyncio
async def test_recover_increments_crash_attempts_and_suspends_over_budget() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("active-ish", max_retries=0)
    goal.status = "active"
    goal.assigned_loop_id = "loop-x"

    recovered = await ce.recover()
    # max_retries=0 → attempts_after_crash=1 > 0 → suspended, not in recovered list
    assert goal.id not in recovered
    after = await ce.get_goal(goal.id)
    assert after is not None
    assert after.status == "suspended"
    assert after.attempts_after_crash == 1
