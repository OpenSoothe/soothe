"""Tests for WorkerPool sticky-affinity scheduling (RFC-222 / IG-677)."""

from __future__ import annotations

import asyncio
import re

import pytest

from soothe.autopilot.worker_pool import (
    WorkerPool,
    WorkerSlot,
    allocate_assignment_loop_id,
    is_autopilot_worker_loop_id,
    parse_job_id_from_loop_id,
)
from soothe.context.models import GoalNode

_LOOP_ID_RE = re.compile(r"^autopilot__[0-9a-f]+__[0-9a-f]{32}$")


class _FakeRunner:
    """Minimal LoopRunnerProtocol stand-in (just needs to exist)."""

    def __init__(self, loop_id: str) -> None:
        self.loop_id = loop_id

    async def run(self, request):  # noqa: ANN001 - tests don't care
        yield None

    async def cancel(self) -> None:
        pass


class _FakeFactory:
    def __init__(self) -> None:
        self.create_calls: list[str] = []

    def create_runner(self, loop_id: str):  # noqa: ANN001
        self.create_calls.append(loop_id)
        return _FakeRunner(loop_id)


def _goal(gid: str, *, depends_on: list[str] | None = None) -> GoalNode:
    return GoalNode(id=gid, description=f"goal {gid}", depends_on=depends_on or [])


async def _pick(
    pool: WorkerPool, goal: GoalNode, *, job_id: str | None = None
) -> WorkerSlot | None:
    return await pool.pick_worker(goal, job_id=job_id or goal.id)


class TestPoolConstruction:
    def test_rejects_zero_max_loops(self) -> None:
        with pytest.raises(ValueError, match="max_loops must be >= 1"):
            WorkerPool(_FakeFactory(), max_loops=0)

    def test_initial_state_empty(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=4)
        assert pool.total_count() == 0
        assert pool.idle_count() == 0
        assert pool.active_count() == 0


class TestPickWorkerSpawn:
    @pytest.mark.asyncio
    async def test_pick_first_goal_spawns_worker(self) -> None:
        factory = _FakeFactory()
        pool = WorkerPool(factory, max_loops=4)
        g = _goal("aabbccdd")
        w = await _pick(pool, g)

        assert isinstance(w, WorkerSlot)
        assert w.status == "active"
        assert w.current_goal_id == "aabbccdd"
        assert _LOOP_ID_RE.match(w.loop_id)
        assert parse_job_id_from_loop_id(w.loop_id) == "aabbccdd"
        assert w.slot_id.startswith("autopilot__slot_")
        assert factory.create_calls == [w.loop_id]
        assert pool.active_count() == 1

    @pytest.mark.asyncio
    async def test_spawns_until_cap_then_returns_none(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        await _pick(pool, _goal("g1"))
        await _pick(pool, _goal("g2"))
        out = await _pick(pool, _goal("g3"))
        assert out is None
        assert pool.total_count() == 2

    @pytest.mark.asyncio
    async def test_assignment_loop_ids_are_unique(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=4)
        w1 = await _pick(pool, _goal("job1"))
        w2 = await _pick(pool, _goal("job1"))
        assert w1 is not None and w2 is not None
        assert w1.loop_id != w2.loop_id
        assert w1.slot_id != w2.slot_id


class TestIdleReuse:
    @pytest.mark.asyncio
    async def test_idle_slot_reused_with_new_loop_id(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        w1 = await _pick(pool, _goal("jobA"), job_id="jobA")
        assert w1 is not None
        old_loop = w1.loop_id
        old_slot = w1.slot_id

        await pool.mark_idle(w1.loop_id)
        w2 = await _pick(pool, _goal("jobB"), job_id="jobB")
        assert w2 is not None
        assert w2.slot_id == old_slot  # slot reused
        assert w2.loop_id != old_loop  # assignment id fresh
        assert parse_job_id_from_loop_id(w2.loop_id) == "jobB"
        assert pool.total_count() == 1

    @pytest.mark.asyncio
    async def test_mark_idle_with_failure_does_not_requeue(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        w = await _pick(pool, _goal("g1"))
        assert w is not None
        await pool.mark_idle(w.loop_id, success=False)

        w2 = await _pick(pool, _goal("g2"))
        assert w2 is not None
        assert w2.slot_id != w.slot_id


class TestStickyAffinity:
    @pytest.mark.asyncio
    async def test_child_prefers_parents_slot(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=4)
        parent = await _pick(pool, _goal("P"), job_id="job1")
        assert parent is not None
        parent_slot = parent.slot_id
        parent_loop = parent.loop_id
        await pool.mark_idle(parent.loop_id)

        child = await _pick(pool, _goal("C", depends_on=["P"]), job_id="job1")
        assert child is not None
        assert child.slot_id == parent_slot
        assert child.loop_id != parent_loop

    @pytest.mark.asyncio
    async def test_sticky_skipped_when_parents_slot_busy(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        parent_worker = await _pick(pool, _goal("P"), job_id="job1")
        assert parent_worker is not None

        child = await _pick(pool, _goal("C", depends_on=["P"]), job_id="job1")
        assert child is not None
        assert child.slot_id != parent_worker.slot_id

    @pytest.mark.asyncio
    async def test_prefer_parameter_accepts_loop_id(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=4)
        w1 = await _pick(pool, _goal("g1"), job_id="job1")
        w2 = await _pick(pool, _goal("g2"), job_id="job1")
        assert w1 and w2
        await pool.mark_idle(w1.loop_id)
        await pool.mark_idle(w2.loop_id)

        preferred_loop = w2.loop_id
        preferred_slot = w2.slot_id
        picked = await pool.pick_worker(_goal("g3"), job_id="job1", prefer=preferred_loop)
        assert picked is not None
        assert picked.slot_id == preferred_slot
        assert picked.loop_id != preferred_loop


class TestRelease:
    @pytest.mark.asyncio
    async def test_release_removes_worker(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        w = await _pick(pool, _goal("g1"))
        assert w is not None

        released = await pool.release_worker(w.loop_id)
        assert released is not None
        assert pool.total_count() == 0
        w2 = await _pick(pool, _goal("g2"))
        assert w2 is not None
        assert w2.slot_id != w.slot_id

    @pytest.mark.asyncio
    async def test_release_unknown_loop_id_returns_none(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        out = await pool.release_worker("autopilot__deadbeef__" + "0" * 32)
        assert out is None


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_picks_get_distinct_workers(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=4)
        goals = [_goal(f"g{i}") for i in range(4)]

        results = await asyncio.gather(*(_pick(pool, g) for g in goals))

        assert all(w is not None for w in results)
        loop_ids = {w.loop_id for w in results if w}
        slot_ids = {w.slot_id for w in results if w}
        assert len(loop_ids) == 4
        assert len(slot_ids) == 4
        assert pool.total_count() == 4

    @pytest.mark.asyncio
    async def test_concurrent_picks_over_cap_some_get_none(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        goals = [_goal(f"g{i}") for i in range(5)]

        results = await asyncio.gather(*(_pick(pool, g) for g in goals))
        assigned = [w for w in results if w is not None]
        none_count = sum(1 for w in results if w is None)
        assert len(assigned) == 2
        assert none_count == 3
        assert pool.total_count() == 2


class TestRecencyCache:
    @pytest.mark.asyncio
    async def test_last_goal_ids_updated_on_release(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=1)
        w = await _pick(pool, _goal("g1"), job_id="job1")
        assert w is not None
        await pool.mark_idle(w.loop_id)
        assert "g1" in w.last_goal_ids

        await _pick(pool, _goal("g2"), job_id="job1")
        await pool.mark_idle(w.loop_id)
        assert "g1" in w.last_goal_ids
        assert "g2" in w.last_goal_ids


class TestLoopIdNamespacing:
    def test_namespace_helper_identifies_autopilot_workers(self) -> None:
        assert is_autopilot_worker_loop_id("autopilot__w001") is True
        assert is_autopilot_worker_loop_id("autopilot__w999") is True
        assert is_autopilot_worker_loop_id("autopilot__aabbccdd__" + "ab" * 16) is True
        assert is_autopilot_worker_loop_id("autopilot__slot_001") is True
        assert is_autopilot_worker_loop_id("client-session-42") is False
        assert is_autopilot_worker_loop_id("autopilot") is False

    def test_allocate_and_parse_round_trip(self) -> None:
        loop_id = allocate_assignment_loop_id("deadbeef")
        assert parse_job_id_from_loop_id(loop_id) == "deadbeef"
        assert _LOOP_ID_RE.match(loop_id)
