"""Tests for InMemoryGoalDispatchContextStore (RFC-222 revised)."""

from __future__ import annotations

import asyncio

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
