"""Tests for process-scoped SQLite checkpoint coalesce flush (IG-647)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from soothe.persistence.sqlite_loop_flush import SqliteLoopFlushCoordinator
from soothe.runner._worker_utils import cancel_orphan_loop_tasks
from soothe.sloop.state.sloop_manager import StrangeLoopStateManager


@pytest.fixture(autouse=True)
async def _reset_sqlite_flush_coordinator():
    await SqliteLoopFlushCoordinator.close_shared_instance()
    yield
    await SqliteLoopFlushCoordinator.close_shared_instance()


@pytest.mark.asyncio
async def test_close_releases_loop_from_process_flush() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        db_path = workspace / "test_loop_checkpoints.db"
        with patch(
            "soothe.sloop.state.sloop_manager.PersistenceDirectoryManager.get_loop_checkpoint_path",
            return_value=db_path,
        ):
            manager = StrangeLoopStateManager(loop_id="async_worker_loop")
            checkpoint = await manager.initialize("thread_001", max_iterations=3)
            goal = manager.start_new_goal("goal")
            checkpoint.goal_history.append(goal)
            checkpoint.current_goal_index = 0
            checkpoint.status = "running"
            await manager.save(checkpoint)

            coord = SqliteLoopFlushCoordinator.existing_instance()
            assert coord is not None
            assert coord._worker_task is not None

            await manager.close()

            with coord._pending_guard:
                assert "async_worker_loop" not in coord._pending


def test_cancel_orphan_loop_tasks_clears_leaked_worker() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def leaked_worker() -> None:
        try:
            await asyncio.wait_for(asyncio.Queue().get(), timeout=3600.0)
        except asyncio.CancelledError:
            raise

    try:
        loop.run_until_complete(asyncio.sleep(0))
        task = loop.create_task(leaked_worker(), name="leaked-checkpoint-flush")
        loop.run_until_complete(asyncio.sleep(0))
        assert not task.done()

        cancel_orphan_loop_tasks(loop, timeout_seconds=5.0)
        assert task.done()
    finally:
        loop.close()


def test_cancel_orphan_loop_tasks_logs_task_names_on_timeout(caplog) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def stubborn_after_cancel() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.Event().wait()

    try:
        loop.run_until_complete(asyncio.sleep(0))
        loop.create_task(stubborn_after_cancel(), name="stuck-increment")
        loop.run_until_complete(asyncio.sleep(0))

        async def _raise_timeout(coro, *args, **kwargs):
            coro.close()
            raise TimeoutError

        with patch(
            "soothe.runner._worker_utils.asyncio.wait_for",
            new=_raise_timeout,
        ):
            with caplog.at_level("WARNING", logger="soothe.runner._worker_utils"):
                cancel_orphan_loop_tasks(loop, timeout_seconds=0.01)

        assert "stuck-increment" in caplog.text
    finally:
        loop.close()


def test_cancel_orphan_loop_tasks_swallows_unexpected_cleanup_error(caplog) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def leaked_worker() -> None:
        await asyncio.sleep(3600.0)

    try:
        loop.run_until_complete(asyncio.sleep(0))
        loop.create_task(leaked_worker(), name="cleanup-crash-task")
        loop.run_until_complete(asyncio.sleep(0))

        async def _raise_runtime_error(coro, *args, **kwargs):
            coro.close()
            raise RuntimeError("cleanup boom")

        with patch(
            "soothe.runner._worker_utils.asyncio.wait_for",
            new=_raise_runtime_error,
        ):
            with caplog.at_level("WARNING", logger="soothe.runner._worker_utils"):
                cancel_orphan_loop_tasks(loop, timeout_seconds=0.01)

        assert "cleanup crashed" in caplog.text
    finally:
        loop.close()
