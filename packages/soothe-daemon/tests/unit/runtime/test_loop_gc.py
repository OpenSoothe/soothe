"""Unit tests for ephemeral loop GC helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_daemon.runtime.loop_gc import purge_loop_execution_data


@pytest.mark.asyncio
async def test_purge_skips_loop_with_active_runner() -> None:
    """A loop with a live runner is protected regardless of persisted status.

    The purge gate checks ``_loop_has_active_runner``, not the ``status``
    string, so a zombie (status=running but no runner) is reclaimable
    while a genuinely active loop is skipped.
    """
    daemon = MagicMock()
    daemon._active_stream_loop_ids = {"loop-1"}
    metadata = {"status": "running"}
    ok = await purge_loop_execution_data(daemon, "loop-1", metadata)
    assert ok is False
    daemon._query_engine.cancel_loop.assert_not_called()


@pytest.mark.asyncio
async def test_purge_reclaims_running_zombie() -> None:
    """A loop marked status=running with NO active runner is purged (zombie)."""
    daemon = MagicMock()
    daemon._active_stream_loop_ids = set()
    daemon._loops_with_active_query = set()
    daemon._query_engine = MagicMock()
    daemon._query_engine._active_runners = {}
    daemon._query_engine._loops_turn_starting = set()
    daemon._query_engine.cancel_loop = AsyncMock()
    daemon._session_manager._sessions = {}
    daemon._loop_input_dispatcher.cleanup_loop = AsyncMock()
    daemon._thread_registry.cleanup_loop.return_value = []
    daemon._runner = None
    daemon._persistence_manager.purge_loop_execution_data = AsyncMock()

    metadata: dict[str, Any] = {
        "status": "running",
    }
    ok = await purge_loop_execution_data(daemon, "loop-zombie", metadata)
    assert ok is True
    daemon._persistence_manager.purge_loop_execution_data.assert_awaited_once_with("loop-zombie")


@pytest.mark.asyncio
async def test_purge_ephemeral_loop_calls_cleanup() -> None:
    daemon = MagicMock()
    daemon._query_engine.cancel_loop = AsyncMock()
    daemon._session_manager._sessions = {}
    daemon._loop_input_dispatcher.cleanup_loop = AsyncMock()
    daemon._thread_registry.cleanup_loop.return_value = []
    daemon._runner = None
    daemon._persistence_manager.purge_loop_execution_data = AsyncMock()

    metadata: dict[str, Any] = {
        "status": "created",
        "current_thread_id": "thr-1",
    }
    ok = await purge_loop_execution_data(daemon, "loop-ephem", metadata)
    assert ok is True
    daemon._persistence_manager.purge_loop_execution_data.assert_awaited_once_with("loop-ephem")


@pytest.mark.asyncio
async def test_collect_loop_thread_ids_uses_checkpoint_scan() -> None:
    """GC discovers fork threads via the LangGraph checkpoint prefix scan."""
    from soothe_daemon.runtime.loop_gc import _collect_loop_thread_ids

    daemon = MagicMock()
    daemon._runner = MagicMock()
    daemon._runner.list_checkpoint_thread_ids = AsyncMock(
        return_value=["loop-1__a3f7c", "loop-1__b2e1d", "loop-1__synth_gc__abc"]
    )
    result = await _collect_loop_thread_ids(daemon, "loop-1")
    assert result == ["loop-1", "loop-1__a3f7c", "loop-1__b2e1d", "loop-1__synth_gc__abc"]
    daemon._runner.list_checkpoint_thread_ids.assert_awaited_once_with("loop-1__")


@pytest.mark.asyncio
async def test_collect_loop_thread_ids_falls_back_when_no_runner() -> None:
    """Without a runner, GC collects only the bare loop_id."""
    from soothe_daemon.runtime.loop_gc import _collect_loop_thread_ids

    daemon = MagicMock()
    daemon._runner = None
    result = await _collect_loop_thread_ids(daemon, "loop-1")
    assert result == ["loop-1"]


@pytest.mark.asyncio
async def test_delete_loop_threads_calls_both_durability_and_checkpoint() -> None:
    """_delete_loop_threads deletes durability metadata + LangGraph checkpoint rows."""
    from soothe_daemon.runtime.loop_gc import _delete_loop_threads

    daemon = MagicMock()
    daemon._runner = MagicMock()
    daemon._runner.delete_persisted_thread = AsyncMock()
    daemon._runner.delete_checkpoint_thread = AsyncMock()

    await _delete_loop_threads(daemon, ["loop-1", "loop-1__a3f7c"])

    assert daemon._runner.delete_persisted_thread.await_count == 2
    assert daemon._runner.delete_checkpoint_thread.await_count == 2
    daemon._runner.delete_persisted_thread.assert_any_await("loop-1")
    daemon._runner.delete_persisted_thread.assert_any_await("loop-1__a3f7c")
    daemon._runner.delete_checkpoint_thread.assert_any_await("loop-1")
    daemon._runner.delete_checkpoint_thread.assert_any_await("loop-1__a3f7c")
