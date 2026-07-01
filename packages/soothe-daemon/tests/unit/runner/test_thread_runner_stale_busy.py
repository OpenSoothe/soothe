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


@pytest.mark.asyncio
async def test_recover_stale_busy_worker_delivers_done_without_last_error() -> None:
    """Clean worker exit with stale busy state should unblock submit with done."""
    pool = ThreadPool.__new__(ThreadPool)
    pool._pending_responses = {}
    pool._workers_by_loop_id = {"loop-abc": "thread-worker-0"}
    pool._mark_worker_idle_and_notify = AsyncMock()
    pool._route_failure_for_dead_busy_worker = AsyncMock()

    worker = _dead_busy_worker()
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


@pytest.mark.asyncio
async def test_recover_stale_busy_worker_routes_error_when_last_error_set() -> None:
    """Unexpected worker failure should still surface the generic error path."""
    pool = ThreadPool.__new__(ThreadPool)
    pool._pending_responses = {"req-123": asyncio.Queue()}
    pool._workers_by_loop_id = {"loop-abc": "thread-worker-0"}
    pool._mark_worker_idle_and_notify = AsyncMock()
    pool._route_failure_for_dead_busy_worker = AsyncMock()
    pool._respawn_worker = AsyncMock()

    worker = _dead_busy_worker()

    with patch(
        "soothe_daemon.runner.thread_runner._pop_worker_last_error",
        return_value="RuntimeError: boom",
    ):
        await pool._handle_dead_worker(worker)

    pool._route_failure_for_dead_busy_worker.assert_awaited_once_with(worker)
