"""Tests for ConcurrencyController (RFC-0009)."""

import asyncio

import pytest

from soothe.core.concurrency import ConcurrencyController
from soothe.protocols.concurrency import ConcurrencyPolicy


async def test_init_from_policy() -> None:
    policy = ConcurrencyPolicy(
        max_parallel_goals=2,
        max_parallel_steps=4,
        global_max_llm_calls=10,
        step_parallelism="max",
    )
    controller = ConcurrencyController(policy)
    assert controller.max_parallel_goals == 2
    assert controller.max_parallel_steps == 4
    assert controller.step_parallelism == "max"


async def test_policy_property() -> None:
    policy = ConcurrencyPolicy(max_parallel_goals=3)
    controller = ConcurrencyController(policy)
    assert controller.policy is policy


async def test_step_parallelism_property() -> None:
    policy = ConcurrencyPolicy(step_parallelism="sequential")
    controller = ConcurrencyController(policy)
    assert controller.step_parallelism == "sequential"


async def test_max_parallel_steps_property() -> None:
    policy = ConcurrencyPolicy(max_parallel_steps=7)
    controller = ConcurrencyController(policy)
    assert controller.max_parallel_steps == 7


async def test_max_parallel_goals_property() -> None:
    policy = ConcurrencyPolicy(max_parallel_goals=5)
    controller = ConcurrencyController(policy)
    assert controller.max_parallel_goals == 5


async def test_acquire_step_releases() -> None:
    policy = ConcurrencyPolicy(max_parallel_steps=1)
    controller = ConcurrencyController(policy)
    entered = False
    async with controller.acquire_step():
        entered = True
    assert entered


async def test_acquire_goal_releases() -> None:
    policy = ConcurrencyPolicy(max_parallel_goals=1)
    controller = ConcurrencyController(policy)
    entered = False
    async with controller.acquire_goal():
        entered = True
    assert entered


async def test_acquire_llm_call_releases() -> None:
    policy = ConcurrencyPolicy(global_max_llm_calls=1)
    controller = ConcurrencyController(policy)
    entered = False
    async with controller.acquire_llm_call():
        entered = True
    assert entered


async def test_max_parallel_steps_blocks() -> None:
    policy = ConcurrencyPolicy(max_parallel_steps=1)
    controller = ConcurrencyController(policy)
    acquired = asyncio.Event()
    released = asyncio.Event()

    async def hold() -> None:
        async with controller.acquire_step():
            acquired.set()
            await released.wait()

    async def try_acquire() -> None:
        async with controller.acquire_step():
            pass

    t1 = asyncio.create_task(hold())
    await acquired.wait()
    t2 = asyncio.create_task(try_acquire())
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(t2), timeout=0.1)
    assert not t2.done()
    released.set()
    await asyncio.wait_for(t2, timeout=1.0)
    await asyncio.wait_for(t1, timeout=1.0)


async def test_max_parallel_goals_blocks() -> None:
    policy = ConcurrencyPolicy(max_parallel_goals=1)
    controller = ConcurrencyController(policy)
    acquired = asyncio.Event()
    released = asyncio.Event()

    async def hold() -> None:
        async with controller.acquire_goal():
            acquired.set()
            await released.wait()

    async def try_acquire() -> None:
        async with controller.acquire_goal():
            pass

    t1 = asyncio.create_task(hold())
    await acquired.wait()
    t2 = asyncio.create_task(try_acquire())
    sleep_task = asyncio.create_task(asyncio.sleep(0.1))
    _, pending = await asyncio.wait([t2, sleep_task], return_when=asyncio.FIRST_COMPLETED)
    assert t2 in pending
    released.set()
    await asyncio.wait_for(t2, timeout=1.0)
    await asyncio.wait_for(t1, timeout=1.0)


async def test_global_llm_limit_blocks() -> None:
    policy = ConcurrencyPolicy(global_max_llm_calls=2)
    controller = ConcurrencyController(policy)
    acquired = asyncio.Event()
    released = asyncio.Event()

    async def hold_two() -> None:
        async with controller.acquire_llm_call():
            async with controller.acquire_llm_call():
                acquired.set()
                await released.wait()

    async def try_acquire() -> None:
        async with controller.acquire_llm_call():
            pass

    t1 = asyncio.create_task(hold_two())
    await acquired.wait()
    t2 = asyncio.create_task(try_acquire())
    sleep_task = asyncio.create_task(asyncio.sleep(0.1))
    _, pending = await asyncio.wait([t2, sleep_task], return_when=asyncio.FIRST_COMPLETED)
    assert t2 in pending
    released.set()
    await asyncio.wait_for(t2, timeout=1.0)
    await asyncio.wait_for(t1, timeout=1.0)


async def test_concurrent_acquire_step() -> None:
    policy = ConcurrencyPolicy(max_parallel_steps=3)
    controller = ConcurrencyController(policy)
    acquired = 0
    release = asyncio.Event()

    async def acquire_and_hold() -> None:
        nonlocal acquired
        async with controller.acquire_step():
            acquired += 1
            await release.wait()

    tasks = [asyncio.create_task(acquire_and_hold()) for _ in range(3)]
    await asyncio.sleep(0.05)
    assert acquired == 3
    release.set()
    await asyncio.gather(*tasks)
