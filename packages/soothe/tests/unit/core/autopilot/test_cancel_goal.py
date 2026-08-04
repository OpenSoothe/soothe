"""Tests for AutopilotService.cancel_goal worker propagation (RFC-222 H8, RFC-625)."""

from __future__ import annotations

import asyncio

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


class _HangingRunner:
    """A runner whose stream never terminates unless the task is cancelled."""

    def __init__(self, loop_id: str) -> None:
        self.loop_id = loop_id
        self.cancel_called = False

    async def run(self, request):  # noqa: ANN001
        # Block forever until the consumer task is cancelled.
        await asyncio.Event().wait()
        yield None  # pragma: no cover

    async def cancel(self) -> None:
        self.cancel_called = True


class _FakeFactory:
    def __init__(self, runner_cls: type = _FakeRunner) -> None:
        self._runner_cls = runner_cls

    def create_runner(self, loop_id: str):  # noqa: ANN001
        return self._runner_cls(loop_id)


def _service(runner_cls: type = _FakeRunner) -> AutopilotService:
    bus = InternalEventBus()
    ce = ContextEngine()
    cfg = AutopilotConfig(max_loops=2, max_parallel_goals=2)
    return AutopilotService(
        ce=ce,
        config=cfg,
        internal_bus=bus,
        runner_factory=_FakeFactory(runner_cls),
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
        worker = await svc._worker_pool.pick_worker(goal, job_id=goal.id)
        assert worker is not None
        # Mark goal active on this worker.
        svc._ce.claim_goal(goal.id, loop_id=worker.loop_id)

        result = await svc.cancel_goal(goal.id, reason="user_cancelled")

        assert worker.runner.cancel_called is True
        assert result is not None
        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_no_retry_even_if_retries_left(self) -> None:
        """Cancellation is terminal regardless of retry budget."""
        svc = _service()
        goal = await svc.submit_task("g", max_retries=5)
        worker = await svc._worker_pool.pick_worker(goal, job_id=goal.id)
        assert worker is not None
        svc._ce.claim_goal(goal.id, loop_id=worker.loop_id)

        result = await svc.cancel_goal(goal.id)

        assert result is not None
        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_cascades_to_descendants(self) -> None:
        """Cancelling a root cancels pending/active children (job cancel)."""
        svc = _service()
        root = await svc.submit_task("root", max_retries=0)
        child = await svc._ce.create_goal("child", parent_id=root.id, source="decomposition")
        grandchild = await svc._ce.create_goal("gc", parent_id=child.id, source="decomposition")

        result = await svc.cancel_goal(root.id)

        assert result is not None
        assert result.status == "cancelled"
        assert (await svc.get_goal(child.id)).status == "cancelled"
        assert (await svc.get_goal(grandchild.id)).status == "cancelled"


class TestCancelGoalNoDeadWorkers:
    """Verify that cancel_goal leaves no dead workers behind (SOJ-04)."""

    @pytest.mark.asyncio
    async def test_worker_slot_returned_to_idle_after_cancel(self) -> None:
        """After cancelling an active goal, the worker slot must be idle."""
        svc = _service()
        goal = await svc.submit_task("g", max_retries=0)
        worker = await svc._worker_pool.pick_worker(goal, job_id=goal.id)
        assert worker is not None
        svc._ce.claim_goal(goal.id, loop_id=worker.loop_id)
        assert worker.status == "active"

        await svc.cancel_goal(goal.id)

        # The slot must be back to idle — no dead workers.
        assert worker.status == "idle"
        assert svc._worker_pool.active_count() == 0
        assert svc._worker_pool.idle_count() == 1

    @pytest.mark.asyncio
    async def test_dispatch_task_cleaned_up_after_cancel(self) -> None:
        """The _dispatch_tasks dict must not retain a dead consumer task."""
        svc = _service()
        goal = await svc.submit_task("g", max_retries=0)
        worker = await svc._worker_pool.pick_worker(goal, job_id=goal.id)
        assert worker is not None
        svc._ce.claim_goal(goal.id, loop_id=worker.loop_id)

        await svc.cancel_goal(goal.id)

        assert goal.id not in svc._dispatch_tasks

    @pytest.mark.asyncio
    async def test_hanging_worker_released_after_cancel(self) -> None:
        """A worker whose stream never terminates must still be released."""
        svc = _service(runner_cls=_HangingRunner)
        goal = await svc.submit_task("g", max_retries=0)
        worker = await svc._worker_pool.pick_worker(goal, job_id=goal.id)
        assert worker is not None
        svc._ce.claim_goal(goal.id, loop_id=worker.loop_id)

        # Simulate dispatch by creating the consumer task.
        async def _noop_stream(goal_id: str, w: object, req: object) -> None:  # noqa: ANN001
            await asyncio.Event().wait()

        svc._dispatch_tasks[goal.id] = asyncio.create_task(_noop_stream(goal.id, worker, None))

        await svc.cancel_goal(goal.id)

        assert worker.runner.cancel_called is True
        assert worker.status == "idle"
        assert svc._worker_pool.active_count() == 0
        assert goal.id not in svc._dispatch_tasks

    @pytest.mark.asyncio
    async def test_cancel_all_open_goals_no_dead_workers(self) -> None:
        """cancel_all_open_goals must also leave no active workers."""
        svc = _service()
        g1 = await svc.submit_task("g1", max_retries=0)
        g2 = await svc.submit_task("g2", max_retries=0)
        w1 = await svc._worker_pool.pick_worker(g1, job_id=g1.id)
        w2 = await svc._worker_pool.pick_worker(g2, job_id=g2.id)
        assert w1 is not None
        assert w2 is not None
        svc._ce.claim_goal(g1.id, loop_id=w1.loop_id)
        svc._ce.claim_goal(g2.id, loop_id=w2.loop_id)

        result = await svc.cancel_all_open_goals()

        assert result["cancelled_count"] == 2
        assert svc._worker_pool.active_count() == 0
        assert svc._worker_pool.idle_count() == 2
        assert len(svc._dispatch_tasks) == 0

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_root_cleans_pending_children(self) -> None:
        """Re-cancelling a cancelled root still cancels pending descendants."""
        svc = _service()
        root = await svc.submit_task("root", max_retries=0)
        child = await svc._ce.create_goal("child", parent_id=root.id, source="decomposition")
        await svc._ce.cancel_goal(root.id, reason="prior")

        result = await svc.cancel_goal(root.id)

        assert result is not None
        assert result.status == "cancelled"
        assert (await svc.get_goal(child.id)).status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_all_open_goals(self) -> None:
        svc = _service()
        a = await svc.submit_task("a", max_retries=0)
        b = await svc.submit_task("b", max_retries=0)
        child = await svc._ce.create_goal("c", parent_id=a.id, source="decomposition")
        await svc._ce.cancel_goal(b.id, reason="already")

        result = await svc.cancel_all_open_goals(reason="bulk")

        assert result["cancelled_count"] == 2
        assert set(result["goal_ids"]) == {a.id, child.id}
        assert (await svc.get_goal(a.id)).status == "cancelled"
        assert (await svc.get_goal(child.id)).status == "cancelled"
        assert (await svc.get_goal(b.id)).status == "cancelled"
