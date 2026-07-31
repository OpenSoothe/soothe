"""Tests for InMemoryGoalDispatchContextStore (RFC-222 revised)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from soothe.autopilot.context_store import (
    GoalDispatchContextStoreProtocol,
    InMemoryGoalDispatchContextStore,
)
from soothe.autopilot.engine_models import (
    Finding,
    GoalDispatchContextContribution,
)


def _contribution(narrative: str) -> GoalDispatchContextContribution:
    return GoalDispatchContextContribution(findings=[Finding(summary=narrative)])


class TestStoreContract:
    """In-memory implementation must satisfy GoalDispatchContextStoreProtocol."""

    def test_satisfies_protocol(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        assert isinstance(store, GoalDispatchContextStoreProtocol)


class TestStoreCRUD:
    @pytest.mark.asyncio
    async def test_put_and_get(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        c = _contribution("hello")
        await store.put("g1", c)
        out = await store.get("g1")
        assert out == c

    @pytest.mark.asyncio
    async def test_get_absent_returns_none(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        assert await store.get("missing") is None

    @pytest.mark.asyncio
    async def test_put_overwrites(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put("g1", _contribution("v1"))
        await store.put("g1", _contribution("v2"))
        out = await store.get("g1")
        assert out is not None
        assert out.findings[0].summary == "v2"

    @pytest.mark.asyncio
    async def test_get_many_only_returns_present(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put("a", _contribution("A"))
        await store.put("c", _contribution("C"))
        out = await store.get_many(["a", "b", "c"])
        assert set(out.keys()) == {"a", "c"}

    @pytest.mark.asyncio
    async def test_delete_returns_existed_flag(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put("a", _contribution("A"))
        assert await store.delete("a") is True
        assert await store.delete("a") is False  # second delete: no-op

    @pytest.mark.asyncio
    async def test_delete_many_counts_actual_removals(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put("a", _contribution("A"))
        await store.put("b", _contribution("B"))
        removed = await store.delete_many(["a", "missing", "b"])
        assert removed == 2
        assert await store.all_goal_ids() == set()

    @pytest.mark.asyncio
    async def test_all_goal_ids(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put("a", _contribution("A"))
        await store.put("b", _contribution("B"))
        assert await store.all_goal_ids() == {"a", "b"}

    @pytest.mark.asyncio
    async def test_written_at_recorded_on_put(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        assert await store.written_at("a") is None
        await store.put("a", _contribution("A"))
        ts1 = await store.written_at("a")
        assert ts1 is not None

        # Overwriting updates the timestamp.
        await asyncio.sleep(0.001)
        await store.put("a", _contribution("A2"))
        ts2 = await store.written_at("a")
        assert ts2 is not None
        assert ts2 >= ts1

    @pytest.mark.asyncio
    async def test_delete_clears_timestamp(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put("a", _contribution("A"))
        await store.delete("a")
        assert await store.written_at("a") is None

    @pytest.mark.asyncio
    async def test_size_helper(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        assert store.size() == 0
        await store.put("a", _contribution("A"))
        await store.put("b", _contribution("B"))
        assert store.size() == 2


# ---- Bounded LRU eviction -------------------------------------------------


class TestLRUEviction:
    @pytest.mark.asyncio
    async def test_evicts_oldest_when_cap_exceeded(self) -> None:
        store = InMemoryGoalDispatchContextStore(max_entries=2)
        await store.put("a", _contribution("A"))
        await store.put("b", _contribution("B"))
        # Access 'a' so 'b' becomes least-recently-used.
        await store.get("a")
        await store.put("c", _contribution("C"))  # cap exceeded → evict 'b'
        assert await store.get("b") is None
        assert await store.get("a") is not None
        assert await store.get("c") is not None
        assert store.size() == 2

    @pytest.mark.asyncio
    async def test_overwrite_does_not_trigger_eviction(self) -> None:
        store = InMemoryGoalDispatchContextStore(max_entries=1)
        await store.put("a", _contribution("v1"))
        await store.put("a", _contribution("v2"))  # overwrite, not a new key
        out = await store.get("a")
        assert out is not None
        assert out.findings[0].summary == "v2"
        assert store.size() == 1

    @pytest.mark.asyncio
    async def test_unbounded_when_max_entries_zero(self) -> None:
        store = InMemoryGoalDispatchContextStore(max_entries=0)
        for i in range(50):
            await store.put(f"g{i}", _contribution(str(i)))
        assert store.size() == 50


# ---- Time-based retention -------------------------------------------------


class TestRetentionEviction:
    @pytest.mark.asyncio
    async def test_expired_entry_evicted_on_get(self) -> None:
        store = InMemoryGoalDispatchContextStore(retention_hours=1)
        await store.put("a", _contribution("A"))
        # Manually backdate the timestamp to simulate age.
        store._timestamps["a"] = datetime.now(UTC) - timedelta(hours=2)
        # Trigger eviction via a read.
        assert await store.get("a") is None
        assert store.size() == 0

    @pytest.mark.asyncio
    async def test_expired_entry_evicted_on_all_goal_ids(self) -> None:
        store = InMemoryGoalDispatchContextStore(retention_hours=1)
        await store.put("fresh", _contribution("F"))
        await store.put("stale", _contribution("S"))
        store._timestamps["stale"] = datetime.now(UTC) - timedelta(hours=3)
        ids = await store.all_goal_ids()
        assert ids == {"fresh"}


# ---- Concurrency safety ---------------------------------------------------


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_puts_are_serialized(self) -> None:
        store = InMemoryGoalDispatchContextStore(max_entries=10)

        # 20 concurrent puts on distinct keys; only 10 survive.
        async def _put(i: int) -> None:
            await store.put(f"g{i}", _contribution(str(i)))

        await asyncio.gather(*[_put(i) for i in range(20)])
        assert store.size() <= 10

    @pytest.mark.asyncio
    async def test_concurrent_get_many_is_consistent(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        for i in range(10):
            await store.put(f"g{i}", _contribution(str(i)))
        # Concurrent reads should all return consistent data.
        results = await asyncio.gather(*[store.get_many([f"g{i}", "missing"]) for i in range(10)])
        for i, r in enumerate(results):
            assert set(r.keys()) == {f"g{i}"}


# ---- Lifecycle -----------------------------------------------------------


class TestClose:
    @pytest.mark.asyncio
    async def test_close_clears_state(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.put("a", _contribution("A"))
        await store.close()
        assert store.size() == 0

    @pytest.mark.asyncio
    async def test_operations_after_close_raise(self) -> None:
        store = InMemoryGoalDispatchContextStore()
        await store.close()
        with pytest.raises(RuntimeError):
            await store.put("a", _contribution("A"))
        with pytest.raises(RuntimeError):
            await store.get("a")
