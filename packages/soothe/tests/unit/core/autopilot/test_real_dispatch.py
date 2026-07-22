"""End-to-end tests for AutopilotService real dispatch (RFC-222 revised, Phase C, RFC-625).

Covers the full path: submit_task → scheduling tick → WorkerPool.pick_worker
→ claim_goal → LoopRunRequest dispatch → fake runner emits GoalCompletionChunk
→ AutopilotService updates ContextEngine state and releases worker.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from soothe.autopilot import AutopilotService
from soothe.autopilot.context_store import InMemoryGoalDispatchContextStore
from soothe.autopilot.workspace_reservation import WorkspaceReservation
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus

# ---- Fakes -------------------------------------------------------------


class _FakeRunner:
    """LoopRunnerProtocol stub that emits a canned GoalCompletionChunk."""

    def __init__(self, loop_id: str, *, outcome: str = "completed") -> None:
        self.loop_id = loop_id
        self._outcome = outcome
        self._cancelled = False
        self.last_request = None

    async def run(self, request):  # noqa: ANN001
        self.last_request = request
        # Simulate a couple of progress chunks first.
        yield ((), "custom", {"type": "soothe.internal.autopilot.progress.plan", "x": 1})
        # Terminal completion chunk.
        yield (
            (),
            "custom",
            {
                "type": "soothe.internal.autopilot.goal_completion",
                "goal_id": request.autopilot_job.goal_id,
                "outcome": self._outcome,
                "attempt": request.autopilot_job.attempt,
                "context_contribution": {
                    "plan_steps_executed": [],
                    "files_touched": {},
                    "findings": [],
                    "tool_call_stats": {"counts_by_name": {}, "failures_by_name": {}},
                },
                "plan_result_status": "complete" if self._outcome == "completed" else "abandoned",
                "evidence_summary": (
                    "Goal completed successfully with substantive evidence and verified outputs."
                    if self._outcome == "completed"
                    else "Worker failed with a substantive error narrative for consensus review."
                ),
            },
        )

    async def cancel(self) -> None:
        self._cancelled = True


class _FakeFactory:
    def __init__(self, *, outcome: str = "completed") -> None:
        self._outcome = outcome
        self.created: list[str] = []

    def create_runner(self, loop_id: str):  # noqa: ANN001
        self.created.append(loop_id)
        return _FakeRunner(loop_id, outcome=self._outcome)


# ---- Helpers -----------------------------------------------------------


def _mock_consensus_model(*, decision: str = "accept", reasoning: str = "test") -> AsyncMock:
    mock_model = AsyncMock()
    mock_model.ainvoke.return_value.type = "ai"
    mock_model.ainvoke.return_value.content = f"DECISION: {decision}\nREASONING: {reasoning}"
    return mock_model


def _service(*, outcome: str = "completed", with_reservation: bool = False) -> AutopilotService:
    bus = InternalEventBus()
    ce = ContextEngine()
    factory = _FakeFactory(outcome=outcome)
    res = WorkspaceReservation() if with_reservation else None
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=2, max_parallel_goals=2),
        internal_bus=bus,
        runner_factory=factory,
        workspace_reservation=res,
        consensus_model=_mock_consensus_model(),
    )
    # Attach a context store so contributions get persisted.
    svc._context_store = InMemoryGoalDispatchContextStore()
    return svc


async def _wait_until(predicate, *, timeout: float = 1.0, interval: float = 0.01) -> bool:
    """Poll a predicate; return True when it succeeds, False on timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


# ---- Tests -------------------------------------------------------------


class TestEndToEndCompleted:
    @pytest.mark.asyncio
    async def test_submit_then_schedule_dispatches_and_completes(self) -> None:
        svc = _service(outcome="completed")
        goal = await svc.submit_task("write a poem")

        # Run one scheduling tick directly — no need to start the full loop.
        await svc._schedule_ready_goals()

        # Wait for the consumer task to finish.
        ok = await _wait_until(
            lambda: not any(t for t in svc._dispatch_tasks.values() if not t.done())
        )
        assert ok, "dispatch task did not complete"

        # Goal transitioned to completed.
        finished = await svc.get_goal(goal.id)
        assert finished is not None
        assert finished.status == "completed"

        # Worker returned to idle.
        assert svc._worker_pool.idle_count() == 1
        assert svc._worker_pool.active_count() == 0

        # Contribution persisted (empty bundle in this test, but key exists).
        store_keys = await svc._context_store.all_goal_ids()
        assert goal.id in store_keys

    @pytest.mark.asyncio
    async def test_workspace_passed_in_loop_run_request(self, tmp_path) -> None:
        svc = _service(outcome="completed")
        ws = str(tmp_path.resolve())
        goal = await svc.submit_task("list files", workspace=ws)

        await svc._schedule_ready_goals()
        await _wait_until(lambda: not any(t for t in svc._dispatch_tasks.values() if not t.done()))

        runner = next(iter(svc._worker_pool._workers.values())).runner
        assert runner.last_request is not None
        assert runner.last_request.client_workspace == ws
        assert runner.last_request.resolve_workspace_path() == ws

        finished = await svc.get_goal(goal.id)
        assert finished is not None
        assert finished.status == "completed"


class TestEndToEndFailed:
    @pytest.mark.asyncio
    async def test_failed_outcome_marks_goal_failed(self) -> None:
        svc = _service(outcome="failed")
        # max_retries=0 so it goes straight to terminal failed
        goal = await svc.submit_task("doomed", max_retries=0)

        await svc._schedule_ready_goals()
        await _wait_until(lambda: not any(t for t in svc._dispatch_tasks.values() if not t.done()))

        finished = await svc.get_goal(goal.id)
        assert finished is not None
        assert finished.status == "failed"
        assert "failed" in (finished.error or "").lower() or "Worker failed" in (
            finished.error or ""
        )


class TestEndToEndReservation:
    @pytest.mark.asyncio
    async def test_workspace_reservation_blocks_overlap(self) -> None:
        """Pre-acquired reservation on the goal workspace blocks dispatch."""
        svc = _service(outcome="completed", with_reservation=True)
        goal = await svc.submit_task("blocked")

        # Goals without workspace use a per-goal sentinel for reservation.
        svc._workspace_reservation.acquire("external-holder", f"$autopilot/goal/{goal.id}")

        await svc._schedule_ready_goals()
        # Goal stays pending — workspace conflict deferred dispatch.
        unchanged = await svc.get_goal(goal.id)
        assert unchanged is not None
        assert unchanged.status == "pending"
        # No worker was spawned.
        assert svc._worker_pool.total_count() == 0

    @pytest.mark.asyncio
    async def test_reservation_released_after_completion(self) -> None:
        svc = _service(outcome="completed", with_reservation=True)
        await svc.submit_task("clean")
        await svc._schedule_ready_goals()
        await _wait_until(lambda: not any(t for t in svc._dispatch_tasks.values() if not t.done()))
        # Reservation released.
        assert svc._workspace_reservation.reservation_count() == 0


class TestParallelDispatch:
    @pytest.mark.asyncio
    async def test_two_goals_run_on_two_workers(self) -> None:
        svc = _service(outcome="completed")
        a = await svc.submit_task("a", priority=80)
        b = await svc.submit_task("b", priority=80)

        await svc._schedule_ready_goals()
        await _wait_until(
            lambda: not any(t for t in svc._dispatch_tasks.values() if not t.done()),
            timeout=2.0,
        )

        a_done = await svc.get_goal(a.id)
        b_done = await svc.get_goal(b.id)
        assert a_done.status == "completed"
        assert b_done.status == "completed"
        # Both workers idle.
        assert svc._worker_pool.idle_count() == 2

    @pytest.mark.asyncio
    async def test_third_goal_deferred_when_pool_full(self) -> None:
        svc = _service(outcome="completed")
        # Submit 3 — only 2 should dispatch in one tick (max_loops=2)
        for i in range(3):
            await svc.submit_task(f"g{i}", priority=50)

        # Block runners so the first two stay busy.
        async def _blocking_run(request):  # noqa: ANN001
            await asyncio.sleep(10)  # noqa: ASYNC110 - intentional block in test fake
            yield None  # pragma: no cover

        # Replace the runner's run with a blocker so the test sees mid-dispatch.
        original_factory = svc._runner_factory.create_runner

        def _slow_factory(loop_id: str):
            r = original_factory(loop_id)
            r.run = _blocking_run  # type: ignore[method-assign]
            return r

        svc._runner_factory.create_runner = _slow_factory  # type: ignore[assignment]

        await svc._schedule_ready_goals()

        # Pool full at max_loops=2 — third goal stayed pending.
        assert svc._worker_pool.active_count() == 2
        all_goals = await svc.list_goals()
        active = [g for g in all_goals if g.status == "active"]
        pending = [g for g in all_goals if g.status == "pending"]
        assert len(active) == 2
        assert len(pending) == 1

        # Cleanup hanging dispatch tasks.
        for t in svc._dispatch_tasks.values():
            t.cancel()
        for t in list(svc._dispatch_tasks.values()):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


class TestNoCompletionChunk:
    @pytest.mark.asyncio
    async def test_worker_exits_without_completion_chunk_marks_failed(self) -> None:
        svc = _service(outcome="completed")

        async def _silent_run(request):  # noqa: ANN001
            # Yield only progress chunks, never a completion chunk.
            yield ((), "custom", {"type": "soothe.internal.autopilot.progress.plan"})

        original_factory = svc._runner_factory.create_runner

        def _silent_factory(loop_id: str):
            r = original_factory(loop_id)
            r.run = _silent_run  # type: ignore[method-assign]
            return r

        svc._runner_factory.create_runner = _silent_factory  # type: ignore[assignment]

        goal = await svc.submit_task("ghosted", max_retries=0)
        await svc._schedule_ready_goals()
        await _wait_until(lambda: not any(t for t in svc._dispatch_tasks.values() if not t.done()))

        finished = await svc.get_goal(goal.id)
        assert finished is not None
        assert finished.status == "failed"
        assert "GoalCompletionChunk" in (finished.error or "")
