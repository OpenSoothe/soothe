"""Tests for AutopilotService.execute_goal end-to-end delegation (RFC-222)."""

from __future__ import annotations

from typing import Any

import pytest

from soothe.config.models import AutonomousConfig
from soothe.core.autopilot.service import AutopilotService, get_active_loop_context
from soothe.core.events.internal_bus import InternalEventBus
from soothe.core.goal_engine import GoalEngine


def _config() -> AutonomousConfig:
    return AutonomousConfig(max_loops=2)


class _Recorder:
    """Records all events emitted on the bus, in order."""

    def __init__(self, bus: InternalEventBus) -> None:
        self.events: list[Any] = []
        for event_type in (
            "soothe.internal.goal.state_changed",
            "soothe.internal.goal.ready",
            "soothe.internal.loop.spawned",
            "soothe.internal.loop.assigned",
            "soothe.internal.loop.idle",
            "soothe.internal.loop.released",
            "soothe.internal.autopilot.pool_changed",
        ):
            bus.subscribe(event_type, self._on_event)

    async def _on_event(self, event: Any) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type for e in self.events]


class TestExecuteGoalHappyPath:
    @pytest.mark.asyncio
    async def test_claims_assigns_loop_executes_and_releases(self) -> None:
        bus = InternalEventBus()
        ge = GoalEngine(internal_bus=bus)
        service = AutopilotService(goal_engine=ge, config=_config(), internal_bus=bus)
        goal = await ge.create_goal("do thing")

        recorder = _Recorder(bus)
        chunks: list[str] = []

        observed_context: list[tuple[str, str] | None] = []

        async def executor(g: Any, loop: Any):
            # Confirm the goal was claimed and the loop_id was stamped.
            assert g.id == goal.id
            assert g.status == "active"
            assert g.assigned_loop_id == loop.loop_id
            # ContextVar must be live for downstream middleware to read.
            observed_context.append(get_active_loop_context())
            yield "chunk-a"
            yield "chunk-b"
            await ge.complete_goal(g.id)

        async for chunk in service.execute_goal(goal.id, executor=executor):
            chunks.append(chunk)

        assert chunks == ["chunk-a", "chunk-b"]
        assert observed_context == [(observed_context[0][0], goal.id)]
        # ContextVar cleared after run
        assert get_active_loop_context() is None
        # Loop ended up idle and counted in goal_to_loop
        assert service._loop_pool.idle_count() == 1
        assert goal.id in service._loop_pool.goal_to_loop

        # Bus saw the expected sequence (subset assertions to keep flexible)
        types = recorder.types()
        assert "soothe.internal.loop.spawned" in types
        assert "soothe.internal.loop.assigned" in types
        # claim_goal emits state_changed only if status changed; goal was
        # already active from ready_goals…but here we never called ready_goals,
        # so claim is the first activator.
        assert any(
            e.type == "soothe.internal.goal.state_changed" and e.new_status == "active"
            for e in recorder.events
        )
        # complete_goal emits state_changed → completed + a pool idle event.
        assert any(
            e.type == "soothe.internal.goal.state_changed" and e.new_status == "completed"
            for e in recorder.events
        )
        assert "soothe.internal.loop.idle" in types

    @pytest.mark.asyncio
    async def test_executor_chunks_pass_through(self) -> None:
        bus = InternalEventBus()
        ge = GoalEngine(internal_bus=bus)
        service = AutopilotService(goal_engine=ge, config=_config(), internal_bus=bus)
        goal = await ge.create_goal("stream")

        async def executor(_g: Any, _loop: Any):
            for i in range(5):
                yield {"i": i}
            await ge.complete_goal(_g.id)

        out = [c async for c in service.execute_goal(goal.id, executor=executor)]
        assert out == [{"i": 0}, {"i": 1}, {"i": 2}, {"i": 3}, {"i": 4}]


class TestExecuteGoalErrorPaths:
    @pytest.mark.asyncio
    async def test_missing_goal_yields_nothing(self) -> None:
        bus = InternalEventBus()
        ge = GoalEngine(internal_bus=bus)
        service = AutopilotService(goal_engine=ge, config=_config(), internal_bus=bus)

        async def executor(_g: Any, _loop: Any):
            yield "should-not-run"
            raise AssertionError("executor must not be called")

        out = [c async for c in service.execute_goal("does-not-exist", executor=executor)]
        assert out == []

    @pytest.mark.asyncio
    async def test_no_capacity_yields_nothing_and_does_not_run(self) -> None:
        bus = InternalEventBus()
        ge = GoalEngine(internal_bus=bus)
        # Cap at 0 so no loop can ever be assigned.
        service = AutopilotService(
            goal_engine=ge, config=AutonomousConfig(max_loops=1), internal_bus=bus
        )
        # Pre-fill the only loop slot with a busy loop.
        from soothe.core.autopilot.loop_pool import LoopHandle

        busy = LoopHandle(loop_id="busy", current_goal_id="other", status="active")
        service._loop_pool.add_loop(busy)

        goal = await ge.create_goal("starved")

        called = {"executor": False}

        async def executor(_g: Any, _loop: Any):
            called["executor"] = True
            yield "x"

        out = [c async for c in service.execute_goal(goal.id, executor=executor)]
        assert out == []
        assert called["executor"] is False
        # Goal should be untouched
        assert goal.status == "pending"
        assert goal.assigned_loop_id is None

    @pytest.mark.asyncio
    async def test_executor_raises_marks_loop_error_and_releases(self) -> None:
        bus = InternalEventBus()
        ge = GoalEngine(internal_bus=bus)
        service = AutopilotService(goal_engine=ge, config=_config(), internal_bus=bus)
        goal = await ge.create_goal("boom")

        recorder = _Recorder(bus)

        class _BoomError(RuntimeError):
            pass

        async def executor(_g: Any, _loop: Any):
            yield "started"
            raise _BoomError("kaboom")

        chunks: list[Any] = []
        with pytest.raises(_BoomError):
            async for c in service.execute_goal(goal.id, executor=executor):
                chunks.append(c)

        assert chunks == ["started"]
        # ContextVar must be cleared even after the executor raised.
        assert get_active_loop_context() is None
        # Loop should be released (not idle) so a fresh one is spawned next time.
        assert service._loop_pool.total_count() == 0
        assert "soothe.internal.loop.released" in recorder.types()

    @pytest.mark.asyncio
    async def test_claim_race_returns_loop_to_pool(self) -> None:
        """If claim_goal fails (goal already terminal), the assigned loop must
        return to the idle queue so subsequent calls can reuse it."""
        bus = InternalEventBus()
        ge = GoalEngine(internal_bus=bus)
        service = AutopilotService(goal_engine=ge, config=_config(), internal_bus=bus)
        goal = await ge.create_goal("racy")
        # Race: complete the goal before execute_goal can claim it.
        await ge.complete_goal(goal.id)

        async def executor(_g: Any, _loop: Any):
            raise AssertionError("executor must not run on claim failure")
            yield  # pragma: no cover  (makes this an async generator)

        out = [c async for c in service.execute_goal(goal.id, executor=executor)]
        assert out == []
        # A loop was spawned by the assignment attempt; it must be back in the
        # idle queue (or pool) so the slot isn't permanently wasted.
        assert len(service._loop_pool.idle_loops) == 1


class TestParallelExecution:
    """Verify concurrent execute_goal calls respect the assignment lock and
    the max_parallel_goals semaphore (RFC-222)."""

    @pytest.mark.asyncio
    async def test_concurrent_goals_get_distinct_loops(self) -> None:
        """N parallel goals must each receive a distinct loop slot."""
        import asyncio as _asyncio

        bus = InternalEventBus()
        ge = GoalEngine(internal_bus=bus)
        service = AutopilotService(
            goal_engine=ge,
            config=AutonomousConfig(max_loops=4, max_parallel_goals=4),
            internal_bus=bus,
        )
        goals = [await ge.create_goal(f"g{i}") for i in range(4)]

        loop_ids_seen: list[str] = []
        gate = _asyncio.Event()

        async def executor(g: Any, loop: Any):
            loop_ids_seen.append(loop.loop_id)
            # Block all goals until the gate releases so they overlap.
            await gate.wait()
            yield None
            await ge.complete_goal(g.id)

        async def run_one(g: Any) -> None:
            async for _ in service.execute_goal(g.id, executor=executor):
                pass

        tasks = [_asyncio.create_task(run_one(g)) for g in goals]
        # Wait until all goals have entered executor()
        while len(loop_ids_seen) < 4:
            await _asyncio.sleep(0.01)
        gate.set()
        await _asyncio.gather(*tasks)

        # Each goal must have a unique loop assignment.
        assert len(set(loop_ids_seen)) == 4
        # Pool never grew past max_loops.
        assert service._loop_pool.total_count() == 4

    @pytest.mark.asyncio
    async def test_max_parallel_goals_caps_in_flight_executions(self) -> None:
        """Sixth goal must wait for one of the first 2 to finish when cap=2."""
        import asyncio as _asyncio

        bus = InternalEventBus()
        ge = GoalEngine(internal_bus=bus)
        service = AutopilotService(
            goal_engine=ge,
            config=AutonomousConfig(max_loops=8, max_parallel_goals=2),
            internal_bus=bus,
        )
        goals = [await ge.create_goal(f"g{i}") for i in range(6)]

        in_flight = 0
        peak = 0
        completed = 0
        gate = _asyncio.Event()

        async def executor(g: Any, _loop: Any):
            nonlocal in_flight, peak, completed
            in_flight += 1
            peak = max(peak, in_flight)
            await gate.wait()
            yield None
            in_flight -= 1
            completed += 1
            await ge.complete_goal(g.id)

        async def run_one(g: Any) -> None:
            async for _ in service.execute_goal(g.id, executor=executor):
                pass

        tasks = [_asyncio.create_task(run_one(g)) for g in goals]
        # Let coroutines reach the semaphore + enter executor.
        for _ in range(20):
            await _asyncio.sleep(0.01)
            if in_flight >= 2:
                break
        assert in_flight == 2, f"expected 2 in-flight, got {in_flight}"
        gate.set()
        await _asyncio.gather(*tasks)

        assert peak == 2, f"max_parallel_goals=2 was violated; peak={peak}"
        assert completed == 6

    @pytest.mark.asyncio
    async def test_assignment_lock_serializes_loop_assignment(self) -> None:
        """The assignment lock keeps loop assignment atomic. Verified by
        forcing all goals to overlap (gate) and asserting distinct loops."""
        import asyncio as _asyncio

        bus = InternalEventBus()
        ge = GoalEngine(internal_bus=bus)
        service = AutopilotService(
            goal_engine=ge,
            config=AutonomousConfig(max_loops=3, max_parallel_goals=3),
            internal_bus=bus,
        )
        goals = [await ge.create_goal(f"g{i}") for i in range(3)]

        assignments: list[str] = []
        gate = _asyncio.Event()

        async def executor(g: Any, loop: Any):
            assignments.append(loop.loop_id)
            await gate.wait()  # force overlap so loops can't be reused
            yield None
            await ge.complete_goal(g.id)

        tasks = [
            _asyncio.create_task(_drain(service.execute_goal(g.id, executor=executor)))
            for g in goals
        ]
        while len(assignments) < 3:
            await _asyncio.sleep(0.01)
        gate.set()
        await _asyncio.gather(*tasks)

        # All three goals were in-flight simultaneously and must have had
        # distinct loop assignments (no two coroutines claimed the same loop).
        assert len(set(assignments)) == 3


async def _drain(gen: Any) -> None:
    async for _ in gen:
        pass


class TestLineageReuse:
    @pytest.mark.asyncio
    async def test_child_goal_reuses_parents_loop(self) -> None:
        bus = InternalEventBus()
        ge = GoalEngine(internal_bus=bus)
        service = AutopilotService(goal_engine=ge, config=_config(), internal_bus=bus)
        parent = await ge.create_goal("parent")
        child = await ge.create_goal("child", parent_id=parent.id)

        async def executor(g: Any, _loop: Any):
            yield "ran"
            await ge.complete_goal(g.id)

        # Run parent first.
        _ = [c async for c in service.execute_goal(parent.id, executor=executor)]
        parent_loop_id = service._loop_pool.goal_to_loop[parent.id]

        # Child should reuse the parent's loop (lineage affinity).
        _ = [c async for c in service.execute_goal(child.id, executor=executor)]
        child_loop_id = service._loop_pool.goal_to_loop[child.id]

        assert parent_loop_id == child_loop_id

    @pytest.mark.asyncio
    async def test_idle_loop_reused_when_no_lineage(self) -> None:
        bus = InternalEventBus()
        ge = GoalEngine(internal_bus=bus)
        service = AutopilotService(goal_engine=ge, config=_config(), internal_bus=bus)
        g1 = await ge.create_goal("g1")
        g2 = await ge.create_goal("g2")  # unrelated

        async def executor(g: Any, _loop: Any):
            yield None
            await ge.complete_goal(g.id)

        _ = [c async for c in service.execute_goal(g1.id, executor=executor)]
        _ = [c async for c in service.execute_goal(g2.id, executor=executor)]

        # With one idle loop available after g1 completes, g2 should reuse it
        # rather than spawning a second loop.
        assert service._loop_pool.total_count() == 1
