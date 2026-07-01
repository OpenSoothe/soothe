"""Tests for per-loop broadcast budget (IG-534 Phase 2.2)."""

from __future__ import annotations

import asyncio

import pytest

from soothe_daemon.runtime.loop_broadcast_budget import LoopBroadcastBudget


@pytest.mark.asyncio
async def test_budget_limits_in_flight_per_loop() -> None:
    budget = LoopBroadcastBudget(max_in_flight_per_loop=1)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with budget.slot("loop-a"):
            entered.set()
            await release.wait()

    holder_task = asyncio.create_task(holder())
    await asyncio.wait_for(entered.wait(), timeout=1.0)

    acquired = asyncio.Event()

    async def waiter() -> None:
        async with budget.slot("loop-a"):
            acquired.set()

    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)
    assert not acquired.is_set()

    release.set()
    await asyncio.wait_for(acquired.wait(), timeout=1.0)
    await holder_task
    await waiter_task


@pytest.mark.asyncio
async def test_budget_isolates_loops() -> None:
    budget = LoopBroadcastBudget(max_in_flight_per_loop=1)

    async with budget.slot("loop-a"):
        async with budget.slot("loop-b"):
            pass
