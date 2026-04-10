"""Tests for ConcurrencyController (RFC-0009)."""

import asyncio

import pytest

from soothe.core.concurrency import ConcurrencyController
from soothe.protocols.concurrency import ConcurrencyPolicy


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_policy_property() -> None:
    policy = ConcurrencyPolicy(max_parallel_goals=3)
    controller = ConcurrencyController(policy)
    assert controller.policy is policy


@pytest.mark.asyncio
async def test_step_parallelism_property() -> None:
    policy = ConcurrencyPolicy(step_parallelism="sequential")
    controller = ConcurrencyController(policy)
    assert controller.step_parallelism == "sequential"


@pytest.mark.asyncio
async def test_max_parallel_steps_property() -> None:
    policy = ConcurrencyPolicy(max_parallel_steps=7)
    controller = ConcurrencyController(policy)
    assert controller.max_parallel_steps == 7


@pytest.mark.asyncio
async def test_max_parallel_goals_property() -> None:
    policy = ConcurrencyPolicy(max_parallel_goals=5)
    controller = ConcurrencyController(policy)
    assert controller.max_parallel_goals == 5


@pytest.mark.asyncio
async def test_acquire_step_releases() -> None:
    policy = ConcurrencyPolicy(max_parallel_steps=1)
    controller = ConcurrencyController(policy)
    entered = False
    async with controller.acquire_step():
        entered = True
    assert entered


@pytest.mark.asyncio
async def test_acquire_goal_releases() -> None:
    policy = ConcurrencyPolicy(max_parallel_goals=1)
    controller = ConcurrencyController(policy)
    entered = False
    async with controller.acquire_goal():
        entered = True
    assert entered


@pytest.mark.asyncio
async def test_acquire_llm_call_releases() -> None:
    policy = ConcurrencyPolicy(global_max_llm_calls=1)
    controller = ConcurrencyController(policy)
    entered = False
    async with controller.acquire_llm_call():
        entered = True
    assert entered


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_unlimited_goal_passes_immediately() -> None:
    """Unlimited goals (limit=0) should allow any number of concurrent executions."""
    policy = ConcurrencyPolicy(max_parallel_goals=0)  # Unlimited
    controller = ConcurrencyController(policy)

    # Verify no semaphore created for unlimited
    assert controller._goal_sem is None
    assert controller.has_goal_limit is False

    acquired = 0
    release = asyncio.Event()

    async def acquire_and_hold() -> None:
        nonlocal acquired
        async with controller.acquire_goal():
            acquired += 1
            await release.wait()

    # Launch many concurrent tasks (more than previous limit)
    tasks = [asyncio.create_task(acquire_and_hold()) for _ in range(20)]
    await asyncio.sleep(0.05)

    # All should acquire immediately (no blocking)
    assert acquired == 20

    release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_unlimited_step_concurrent_execution() -> None:
    """Unlimited steps (limit=0) should allow any number of concurrent executions."""
    policy = ConcurrencyPolicy(max_parallel_steps=0)  # Unlimited
    controller = ConcurrencyController(policy)

    # Verify no semaphore created for unlimited
    assert controller._step_sem is None
    assert controller.has_step_limit is False

    acquired = 0
    release = asyncio.Event()

    async def acquire_and_hold() -> None:
        nonlocal acquired
        async with controller.acquire_step():
            acquired += 1
            await release.wait()

    # Launch many concurrent tasks (more than previous limit)
    tasks = [asyncio.create_task(acquire_and_hold()) for _ in range(20)]
    await asyncio.sleep(0.05)

    # All should acquire immediately (no blocking)
    assert acquired == 20

    release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_unlimited_llm_calls() -> None:
    """Unlimited LLM calls (limit=0) should disable circuit breaker."""
    policy = ConcurrencyPolicy(global_max_llm_calls=0)  # Unlimited
    controller = ConcurrencyController(policy)

    # Verify no semaphore created for unlimited
    assert controller._llm_sem is None
    assert controller.has_llm_limit is False

    acquired = 0
    release = asyncio.Event()

    async def acquire_and_hold() -> None:
        nonlocal acquired
        async with controller.acquire_llm_call():
            acquired += 1
            await release.wait()

    # Launch many concurrent tasks (more than previous limit)
    tasks = [asyncio.create_task(acquire_and_hold()) for _ in range(30)]
    await asyncio.sleep(0.05)

    # All should acquire immediately (no circuit breaker blocking)
    assert acquired == 30

    release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_mixed_limits() -> None:
    """Test controller with some limits active, others unlimited."""
    policy = ConcurrencyPolicy(
        max_parallel_goals=0,  # Unlimited
        max_parallel_steps=2,  # Limited
        global_max_llm_calls=0,  # Unlimited
    )
    controller = ConcurrencyController(policy)

    # Verify correct semaphore creation
    assert controller._goal_sem is None
    assert controller._step_sem is not None
    assert controller._llm_sem is None

    assert controller.has_goal_limit is False
    assert controller.has_step_limit is True
    assert controller.has_llm_limit is False

    # Test unlimited goal passes through
    acquired_goal = 0
    async with controller.acquire_goal():
        acquired_goal += 1
    assert acquired_goal == 1

    # Test limited step blocks correctly
    acquired_step = 0
    release = asyncio.Event()

    async def hold_step() -> None:
        nonlocal acquired_step
        async with controller.acquire_step():
            acquired_step += 1
            await release.wait()

    # Launch 3 tasks (limit is 2, so third should block)
    tasks = [asyncio.create_task(hold_step()) for _ in range(3)]
    await asyncio.sleep(0.05)

    # Only 2 should acquire (limit is 2)
    assert acquired_step == 2

    release.set()
    await asyncio.gather(*tasks)
    assert acquired_step == 3  # Third acquired after release


@pytest.mark.asyncio
async def test_zero_policy_initialization() -> None:
    """Verify controller handles all-0 policy correctly."""
    policy = ConcurrencyPolicy(
        max_parallel_goals=0,
        max_parallel_steps=0,
        max_parallel_subagents=0,
        global_max_llm_calls=0,
    )
    controller = ConcurrencyController(policy)

    # Verify all semaphores are None (unlimited mode)
    assert controller._goal_sem is None
    assert controller._step_sem is None
    assert controller._llm_sem is None

    # Verify all has_*_limit properties return False
    assert controller.has_goal_limit is False
    assert controller.has_step_limit is False
    assert controller.has_llm_limit is False

    # Verify acquisition passes through without blocking
    async with controller.acquire_goal():
        pass
    async with controller.acquire_step():
        pass
    async with controller.acquire_llm_call():
        pass
