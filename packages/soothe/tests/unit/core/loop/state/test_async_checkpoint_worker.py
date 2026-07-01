"""Tests for async checkpoint flush worker lifecycle (RFC-803 Phase 6)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from soothe.foundation.sloop.state.sloop_manager import (
    StrangeLoopStateManager,
    _is_async_loop_runtime_error,
)

from soothe.runner._worker_utils import cancel_orphan_loop_tasks


def test_is_async_loop_runtime_error() -> None:
    assert _is_async_loop_runtime_error(RuntimeError("no running event loop"))
    assert _is_async_loop_runtime_error(RuntimeError("Event loop is closed"))
    assert _is_async_loop_runtime_error(RuntimeError("Queue is bound to a different event loop"))
    assert not _is_async_loop_runtime_error(RuntimeError("other failure"))


@pytest.mark.asyncio
async def test_close_stops_flush_worker() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        db_path = workspace / "test_loop_checkpoints.db"
        with patch(
            "soothe.foundation.sloop.state.sloop_manager.PersistenceDirectoryManager.get_loop_checkpoint_path",
            return_value=db_path,
        ):
            manager = StrangeLoopStateManager(loop_id="async_worker_loop", workspace=workspace)
            checkpoint = await manager.initialize("thread_001", max_iterations=3)
            goal = manager.start_new_goal("goal")
            checkpoint.goal_history.append(goal)
            checkpoint.current_goal_index = 0
            checkpoint.status = "running"
            await manager.save(checkpoint)

            assert manager._worker_started is True
            assert manager._flush_worker is not None

            await manager.close()

            assert manager._worker_started is False
            assert manager._flush_worker is None
            assert manager._pending_saves is None


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
        task = loop.create_task(leaked_worker())
        loop.run_until_complete(asyncio.sleep(0))
        assert not task.done()

        cancel_orphan_loop_tasks(loop)
        assert task.done()
    finally:
        loop.close()
