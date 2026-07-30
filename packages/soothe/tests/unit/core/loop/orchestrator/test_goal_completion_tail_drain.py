"""Tests for goal-completion tail persistence drain before state manager close."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.stages.complete.finalize import (
    await_goal_completion_tail_persistence,
)


@pytest.mark.asyncio
async def test_await_goal_completion_tail_persistence_waits_for_task() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_tail() -> None:
        started.set()
        await release.wait()

    ctx = Mock(spec=LoopRuntimeContext)
    ctx.state_manager = Mock(loop_id="loop-await-test")
    ctx.tail_persistence_task = asyncio.create_task(_slow_tail())

    wait_task = asyncio.create_task(
        await_goal_completion_tail_persistence(ctx, timeout_seconds=5.0)
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert not wait_task.done()

    release.set()
    await wait_task
    assert ctx.tail_persistence_task.done()


@pytest.mark.asyncio
async def test_await_goal_completion_tail_persistence_cancels_on_timeout() -> None:
    async def _never_finishes() -> None:
        await asyncio.Event().wait()

    ctx = Mock(spec=LoopRuntimeContext)
    ctx.state_manager = Mock(loop_id="loop-timeout-test")
    task = asyncio.create_task(_never_finishes())
    ctx.tail_persistence_task = task

    await await_goal_completion_tail_persistence(ctx, timeout_seconds=0.05)
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_close_blocks_async_flush_worker_restart() -> None:
    from soothe.persistence.sqlite_loop_flush import SqliteLoopFlushCoordinator
    from soothe.sloop.state.sloop_manager import StrangeLoopStateManager

    await SqliteLoopFlushCoordinator.close_shared_instance()
    manager = StrangeLoopStateManager(loop_id="closed-loop-test")

    await manager.close()
    assert manager._closed is True

    checkpoint = Mock()
    checkpoint.updated_at = None
    checkpoint.status = "idle"
    manager._do_save_checkpoint = AsyncMock()

    await manager._save_checkpoint_to_db(checkpoint)
    manager._do_save_checkpoint.assert_awaited_once()
    await SqliteLoopFlushCoordinator.close_shared_instance()
    assert SqliteLoopFlushCoordinator.existing_instance() is None
    coord = SqliteLoopFlushCoordinator.existing_instance()
    assert coord is None


@pytest.mark.asyncio
async def test_tail_persistence_chains_instead_of_cancelling_prior() -> None:
    """A second goal must await the first tail persist, not cancel it."""
    from soothe.sloop.stages.complete.finalize import (
        _start_goal_completion_tail_persistence,
    )

    order: list[str] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    ctx = Mock(spec=LoopRuntimeContext)
    ctx.state_manager = Mock(loop_id="loop-chain-test")
    ctx.ce = Mock()
    ctx.loop_state = Mock()
    ctx.tail_persistence_task = None

    async def _first_tail() -> None:
        order.append("first-start")
        first_started.set()
        await release_first.wait()
        order.append("first-done")

    ctx.tail_persistence_task = asyncio.create_task(_first_tail())
    await asyncio.wait_for(first_started.wait(), timeout=1.0)

    with patch(
        "soothe.sloop.stages.complete.finalize._goal_completion_tail_persistence",
        new=AsyncMock(side_effect=lambda **_kwargs: order.append("second-done")),
    ):
        _start_goal_completion_tail_persistence(
            ctx,
            goal_record=Mock(goal_id="g2"),
        )
        release_first.set()
        await await_goal_completion_tail_persistence(ctx, timeout_seconds=2.0)

    assert order == ["first-start", "first-done", "second-done"]
    assert not ctx.tail_persistence_task.cancelled()
