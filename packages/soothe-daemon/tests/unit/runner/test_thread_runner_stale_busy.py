"""Tests for stale busy-state recovery when worker threads exit after lost ``done``."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe_daemon.runner.thread_runner import ThreadPool, WorkerThreadState, WorkerThreadStatus


def _dead_busy_worker(*, worker_id: str = "thread-worker-0") -> WorkerThreadState:
    thread = MagicMock()
    thread.is_alive.return_value = False
    return WorkerThreadState(
        thread=thread,
        request_queue=MagicMock(),
        response_queue=MagicMock(),
        cancel_event=MagicMock(),
        stop_event=MagicMock(),
        worker_id=worker_id,
        status=WorkerThreadStatus.BUSY,
        current_loop_id="loop-abc",
        current_request_id="req-123",
    )


def _dead_idle_scaled_worker(*, worker_id: str = "thread-worker-9") -> WorkerThreadState:
    thread = MagicMock()
    thread.is_alive.return_value = False
    return WorkerThreadState(
        thread=thread,
        request_queue=MagicMock(),
        response_queue=MagicMock(),
        cancel_event=MagicMock(),
        stop_event=MagicMock(),
        worker_id=worker_id,
        is_baseline=False,
        status=WorkerThreadStatus.IDLE,
    )


@pytest.mark.asyncio
async def test_recover_stale_busy_worker_delivers_done_without_last_error() -> None:
    """Clean worker exit with stale busy state should unblock submit with done."""
    worker = _dead_busy_worker()
    pool = ThreadPool.__new__(ThreadPool)
    pool._pending_responses = {}
    pool._workers_by_loop_id = {"loop-abc": "thread-worker-0"}
    pool._min_pool_size = 2
    pool._workers = {"thread-worker-0": worker}
    pool._mark_worker_idle_and_notify = AsyncMock()
    pool._route_failure_for_dead_busy_worker = AsyncMock()
    pool._respawn_worker = AsyncMock()

    response_queue: asyncio.Queue = asyncio.Queue()
    pool._pending_responses["req-123"] = response_queue

    with patch(
        "soothe_daemon.runner.thread_runner._pop_worker_last_error",
        return_value=None,
    ):
        await pool._handle_dead_worker(worker)

    msg_type, payload = await asyncio.wait_for(response_queue.get(), timeout=1.0)
    assert msg_type == "done"
    assert payload is None
    pool._route_failure_for_dead_busy_worker.assert_not_awaited()
    pool._mark_worker_idle_and_notify.assert_awaited_once_with(worker)
    assert "req-123" not in pool._pending_responses
    assert "loop-abc" not in pool._workers_by_loop_id
    pool._respawn_worker.assert_awaited_once()


@pytest.mark.asyncio
async def test_recover_stale_busy_worker_routes_error_when_last_error_set() -> None:
    """Unexpected worker failure should still surface the generic error path."""
    worker = _dead_busy_worker()
    pool = ThreadPool.__new__(ThreadPool)
    pool._pending_responses = {"req-123": asyncio.Queue()}
    pool._workers_by_loop_id = {"loop-abc": "thread-worker-0"}
    pool._min_pool_size = 2
    pool._workers = {"thread-worker-0": worker}
    pool._mark_worker_idle_and_notify = AsyncMock()
    pool._route_failure_for_dead_busy_worker = AsyncMock()
    pool._respawn_worker = AsyncMock()

    with patch(
        "soothe_daemon.runner.thread_runner._pop_worker_last_error",
        return_value="RuntimeError: boom",
    ):
        await pool._handle_dead_worker(worker)

    pool._route_failure_for_dead_busy_worker.assert_awaited_once_with(worker)
    pool._respawn_worker.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_dead_worker_removes_scaled_idle_exit_without_respawn() -> None:
    """Scaled workers that idle out should shrink the pool, not respawn."""
    pool = ThreadPool.__new__(ThreadPool)
    pool._min_pool_size = 2
    pool._workers = {}
    pool._notify_worker_slot_available = AsyncMock()
    pool._respawn_worker = AsyncMock()

    worker = _dead_idle_scaled_worker()
    pool._workers[worker.worker_id] = worker

    with patch(
        "soothe_daemon.runner.thread_runner._pop_worker_last_error",
        return_value=None,
    ):
        await pool._handle_dead_worker(worker)

    assert worker.worker_id not in pool._workers
    pool._respawn_worker.assert_not_awaited()
    pool._notify_worker_slot_available.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_dead_worker_respawns_baseline_when_below_min() -> None:
    """Unexpected baseline death with live count below min should respawn."""
    pool = ThreadPool.__new__(ThreadPool)
    pool._min_pool_size = 2
    pool._workers = {}
    pool._route_failure_for_dead_busy_worker = AsyncMock()
    pool._respawn_worker = AsyncMock()

    thread = MagicMock()
    thread.is_alive.return_value = False
    worker = WorkerThreadState(
        thread=thread,
        request_queue=MagicMock(),
        response_queue=MagicMock(),
        cancel_event=MagicMock(),
        stop_event=MagicMock(),
        worker_id="thread-worker-0",
        is_baseline=True,
        status=WorkerThreadStatus.IDLE,
    )
    pool._workers[worker.worker_id] = worker

    with patch(
        "soothe_daemon.runner.thread_runner._pop_worker_last_error",
        return_value="RuntimeError: boom",
    ):
        await pool._handle_dead_worker(worker)

    pool._respawn_worker.assert_awaited_once_with(worker, is_baseline=True)


@pytest.mark.asyncio
async def test_handle_dead_worker_respawns_baseline_after_max_requests() -> None:
    """Baseline workers that exit after max_requests must respawn even when live >= min."""
    pool = ThreadPool.__new__(ThreadPool)
    pool._min_pool_size = 2
    pool._workers = {}
    pool._respawn_worker = AsyncMock()
    pool._remove_worker_slot = AsyncMock()

    thread = MagicMock()
    thread.is_alive.return_value = False
    worker = WorkerThreadState(
        thread=thread,
        request_queue=MagicMock(),
        response_queue=MagicMock(),
        cancel_event=MagicMock(),
        stop_event=MagicMock(),
        worker_id="thread-worker-0",
        is_baseline=True,
        status=WorkerThreadStatus.IDLE,
    )
    other = WorkerThreadState(
        thread=MagicMock(is_alive=MagicMock(return_value=True)),
        request_queue=MagicMock(),
        response_queue=MagicMock(),
        cancel_event=MagicMock(),
        stop_event=MagicMock(),
        worker_id="thread-worker-1",
        is_baseline=True,
        status=WorkerThreadStatus.IDLE,
    )
    pool._workers = {worker.worker_id: worker, other.worker_id: other}

    with patch(
        "soothe_daemon.runner.thread_runner._pop_worker_last_error",
        return_value=None,
    ):
        await pool._handle_dead_worker(worker)

    pool._remove_worker_slot.assert_not_awaited()
    pool._respawn_worker.assert_awaited_once_with(worker, is_baseline=True)
