"""Tests for worker ``ready`` signal after post-run cleanup."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_daemon.runner.thread_runner import (
    _TERMINAL_RESPONSE_TYPES,
    _WORKER_READY_TIMEOUT_SECONDS,
    ThreadPool,
    WorkerThreadState,
    WorkerThreadStatus,
)


def _busy_worker(*, worker_id: str = "thread-worker-0") -> WorkerThreadState:
    return WorkerThreadState(
        thread=MagicMock(is_alive=MagicMock(return_value=True)),
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
async def test_finish_request_waits_for_ready_before_marking_idle() -> None:
    """Worker must stay busy/cleaning until ``ready`` arrives."""
    worker = _busy_worker()
    pool = ThreadPool.__new__(ThreadPool)
    pool._workers_by_loop_id = {"loop-abc": worker.worker_id}
    pool._pending_responses = {"req-123": asyncio.Queue()}
    pool._metrics_requests_total = 0
    pool._metrics_ready_timeout_recoveries = 0
    pool._metrics_latencies = []
    pool._worker_ready_timeout_seconds = _WORKER_READY_TIMEOUT_SECONDS

    async def _mark_idle(w: WorkerThreadState) -> None:
        w.mark_idle()

    pool._mark_worker_idle_and_notify = AsyncMock(side_effect=_mark_idle)

    response_queue: asyncio.Queue = asyncio.Queue()

    finish_task = asyncio.create_task(
        pool._finish_request_after_terminal(
            worker,
            "loop-abc",
            "req-123",
            response_queue,
            start_time=datetime.now(),
        )
    )

    await asyncio.sleep(0.05)
    assert worker.status == WorkerThreadStatus.CLEANING_UP
    pool._mark_worker_idle_and_notify.assert_not_awaited()

    await response_queue.put(("ready", None))
    await finish_task

    pool._mark_worker_idle_and_notify.assert_awaited_once_with(worker)
    assert worker.status == WorkerThreadStatus.IDLE
    assert "loop-abc" not in pool._workers_by_loop_id
    assert "req-123" not in pool._pending_responses


@pytest.mark.asyncio
async def test_finish_request_skips_wait_when_ready_seen_early() -> None:
    """Cleanup should not block if ``ready`` was consumed before terminal frame."""
    worker = _busy_worker()
    pool = ThreadPool.__new__(ThreadPool)
    pool._workers_by_loop_id = {"loop-abc": worker.worker_id}
    pool._pending_responses = {"req-123": asyncio.Queue()}
    pool._metrics_requests_total = 0
    pool._metrics_ready_timeout_recoveries = 0
    pool._metrics_latencies = []
    pool._worker_ready_timeout_seconds = _WORKER_READY_TIMEOUT_SECONDS

    async def _mark_idle(w: WorkerThreadState) -> None:
        w.mark_idle()

    pool._mark_worker_idle_and_notify = AsyncMock(side_effect=_mark_idle)

    response_queue: asyncio.Queue = asyncio.Queue()
    await pool._finish_request_after_terminal(
        worker,
        "loop-abc",
        "req-123",
        response_queue,
        start_time=datetime.now(),
        ready_already_received=True,
    )

    pool._mark_worker_idle_and_notify.assert_awaited_once_with(worker)
    assert worker.status == WorkerThreadStatus.IDLE
    assert "loop-abc" not in pool._workers_by_loop_id
    assert "req-123" not in pool._pending_responses


@pytest.mark.asyncio
async def test_finish_request_recycles_worker_when_ready_timeout() -> None:
    """If ready never arrives, force-cancel worker and release loop mapping."""
    worker = _busy_worker()
    pool = ThreadPool.__new__(ThreadPool)
    pool._workers_by_loop_id = {"loop-abc": worker.worker_id}
    pool._pending_responses = {"req-123": asyncio.Queue()}
    pool._metrics_requests_total = 0
    pool._metrics_ready_timeout_recoveries = 0
    pool._metrics_latencies = []
    pool._worker_ready_timeout_seconds = 0.01
    pool._mark_worker_idle_and_notify = AsyncMock()
    pool.force_cancel_worker = AsyncMock()

    response_queue: asyncio.Queue = asyncio.Queue()
    await pool._finish_request_after_terminal(
        worker,
        "loop-abc",
        "req-123",
        response_queue,
        start_time=datetime.now(),
    )

    pool._mark_worker_idle_and_notify.assert_not_awaited()
    pool.force_cancel_worker.assert_awaited_once_with(worker.worker_id, timeout=1.0)
    assert "loop-abc" not in pool._workers_by_loop_id
    assert "req-123" not in pool._pending_responses
    assert pool._metrics_requests_total == 1
    assert pool._metrics_ready_timeout_recoveries == 1
    assert pool._metrics_latencies


def test_terminal_response_types_include_done_and_error() -> None:
    assert "done" in _TERMINAL_RESPONSE_TYPES
    assert "error" in _TERMINAL_RESPONSE_TYPES
