"""Tests for WorkerPool sticky-affinity scheduling (RFC-222 revised, RFC-625)."""

from __future__ import annotations

import asyncio

import pytest

from soothe.autopilot.worker_pool import (
    WorkerPool,
    WorkerSlot,
    is_autopilot_worker_loop_id,
)
from soothe.context.models import GoalNode

# ---- Fakes -------------------------------------------------------------


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


# ---- Basic API ---------------------------------------------------------


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
        g = _goal("g1")
        w = await pool.pick_worker(g)

        assert isinstance(w, WorkerSlot)
        assert w.status == "active"
        assert w.current_goal_id == "g1"
        assert w.loop_id.startswith("autopilot__w")
        assert factory.create_calls == [w.loop_id]
        assert pool.active_count() == 1

    @pytest.mark.asyncio
    async def test_spawns_until_cap_then_returns_none(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        await pool.pick_worker(_goal("g1"))
        await pool.pick_worker(_goal("g2"))
        # Cap reached, no idle workers — should return None
        out = await pool.pick_worker(_goal("g3"))
        assert out is None
        assert pool.total_count() == 2

    @pytest.mark.asyncio
    async def test_loop_ids_are_sequential(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=4)
        w1 = await pool.pick_worker(_goal("g1"))
        w2 = await pool.pick_worker(_goal("g2"))
        assert w1 is not None and w2 is not None
        assert w1.loop_id < w2.loop_id


class TestIdleReuse:
    @pytest.mark.asyncio
    async def test_idle_worker_reused_for_unrelated_goal(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        w1 = await pool.pick_worker(_goal("g1"))
        assert w1 is not None

        await pool.mark_idle(w1.loop_id)
        w2 = await pool.pick_worker(_goal("g2"))
        assert w2 is not None
        assert w2.loop_id == w1.loop_id  # reused
        assert pool.total_count() == 1  # no new spawn

    @pytest.mark.asyncio
    async def test_mark_idle_with_failure_does_not_requeue(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        w = await pool.pick_worker(_goal("g1"))
        assert w is not None
        await pool.mark_idle(w.loop_id, success=False)

        # Worker is in error state; new pick should NOT reuse it.
        w2 = await pool.pick_worker(_goal("g2"))
        assert w2 is not None
        assert w2.loop_id != w.loop_id


class TestStickyAffinity:
    @pytest.mark.asyncio
    async def test_child_prefers_parents_worker(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=4)
        parent = await pool.pick_worker(_goal("P"))
        assert parent is not None
        await pool.mark_idle(parent.loop_id)

        # Child of P should land on P's worker.
        child = await pool.pick_worker(_goal("C", depends_on=["P"]))
        assert child is not None
        assert child.loop_id == parent.loop_id

    @pytest.mark.asyncio
    async def test_sticky_skipped_when_parents_worker_busy(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        parent_worker = await pool.pick_worker(_goal("P"))
        assert parent_worker is not None
        # Don't mark idle — worker is still busy.

        # Child of P comes in; should NOT take the busy worker.
        child = await pool.pick_worker(_goal("C", depends_on=["P"]))
        assert child is not None
        assert child.loop_id != parent_worker.loop_id

    @pytest.mark.asyncio
    async def test_prefer_parameter_takes_precedence(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=4)
        w1 = await pool.pick_worker(_goal("g1"))
        w2 = await pool.pick_worker(_goal("g2"))
        assert w1 and w2
        await pool.mark_idle(w1.loop_id)
        await pool.mark_idle(w2.loop_id)

        # Both idle; explicit prefer wins.
        picked = await pool.pick_worker(_goal("g3"), prefer=w2.loop_id)
        assert picked is not None
        assert picked.loop_id == w2.loop_id


class TestRelease:
    @pytest.mark.asyncio
    async def test_release_removes_worker(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        w = await pool.pick_worker(_goal("g1"))
        assert w is not None

        released = await pool.release_worker(w.loop_id)
        assert released is not None
        assert pool.total_count() == 0
        # A subsequent pick must spawn fresh.
        w2 = await pool.pick_worker(_goal("g2"))
        assert w2 is not None
        assert w2.loop_id != w.loop_id

    @pytest.mark.asyncio
    async def test_release_unknown_loop_id_returns_none(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        out = await pool.release_worker("autopilot__w999")
        assert out is None


class TestConcurrency:
    """The assignment lock must serialize concurrent pick_worker calls."""

    @pytest.mark.asyncio
    async def test_concurrent_picks_get_distinct_workers(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=4)
        goals = [_goal(f"g{i}") for i in range(4)]

        results = await asyncio.gather(*(pool.pick_worker(g) for g in goals))

        assert all(w is not None for w in results)
        loop_ids = {w.loop_id for w in results if w}
        assert len(loop_ids) == 4
        assert pool.total_count() == 4

    @pytest.mark.asyncio
    async def test_concurrent_picks_over_cap_some_get_none(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=2)
        goals = [_goal(f"g{i}") for i in range(5)]

        results = await asyncio.gather(*(pool.pick_worker(g) for g in goals))
        assigned = [w for w in results if w is not None]
        none_count = sum(1 for w in results if w is None)
        assert len(assigned) == 2
        assert none_count == 3
        assert pool.total_count() == 2


class TestRecencyCache:
    @pytest.mark.asyncio
    async def test_last_goal_ids_updated_on_release(self) -> None:
        pool = WorkerPool(_FakeFactory(), max_loops=1)
        w = await pool.pick_worker(_goal("g1"))
        assert w is not None
        await pool.mark_idle(w.loop_id)
        assert "g1" in w.last_goal_ids

        # Reuse the worker for g2 - g1 still in recency.
        await pool.pick_worker(_goal("g2"))
        await pool.mark_idle(w.loop_id)
        assert "g1" in w.last_goal_ids
        assert "g2" in w.last_goal_ids


class TestLoopIdNamespacing:
    def test_namespace_helper_identifies_autopilot_workers(self) -> None:
        assert is_autopilot_worker_loop_id("autopilot__w001") is True
        assert is_autopilot_worker_loop_id("autopilot__w999") is True
        assert is_autopilot_worker_loop_id("client-session-42") is False
        assert is_autopilot_worker_loop_id("autopilot") is False
