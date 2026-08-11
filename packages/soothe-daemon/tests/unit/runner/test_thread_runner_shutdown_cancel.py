"""Regression tests for cooperative cancel on ThreadPool shutdown.

See ``stream_cancel.py:emit_terminal_for_cancelled_error`` — it classifies a
leaked ``CancelledError`` as cooperative (cancelled terminal) vs unexpected
(RuntimeError) based on ``cancel_event.is_set()``. Without setting
``cancel_event`` on busy workers during shutdown, the in-flight stream is torn
down by the event loop and reported as the spurious "unexpected cancellation"
RuntimeError instead of a clean cancelled terminal.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from soothe_daemon.runner.thread_runner import (
    ThreadPool,
    WorkerThreadState,
    WorkerThreadStatus,
)


def _live_busy_worker(*, worker_id: str = "thread-worker-0") -> WorkerThreadState:
    """A worker that looks alive and has an in-flight request."""
    thread = MagicMock()
    thread.is_alive.return_value = True
    # join() is a no-op so the test does not block on the real thread.
    thread.join = MagicMock()
    cancel_event = threading.Event()
    stop_event = threading.Event()
    request_queue = MagicMock()
    return WorkerThreadState(
        thread=thread,
        request_queue=request_queue,
        response_queue=MagicMock(),
        cancel_event=cancel_event,
        stop_event=stop_event,
        worker_id=worker_id,
        is_baseline=True,
        status=WorkerThreadStatus.BUSY,
        current_loop_id="loop-abc",
        current_request_id="req-123",
    )


def _make_pool(workers: dict[str, WorkerThreadState]) -> ThreadPool:
    pool = ThreadPool.__new__(ThreadPool)
    pool._workers = workers
    pool._workers_by_loop_id = {
        w.current_loop_id: wid for wid, w in workers.items() if w.current_loop_id
    }
    pool._pending_responses = {}
    pool._abandon_drain_tasks = set()
    pool._health_task = None
    pool._worker_available = None
    pool._running = True
    return pool


@pytest.mark.asyncio
async def test_shutdown_sets_cancel_event_for_busy_worker() -> None:
    """A busy worker must get cancel_event set on shutdown so the in-flight
    stream unwinds as a cooperative cancel, not an unexpected-cancellation
    RuntimeError."""
    worker = _live_busy_worker()
    pool = _make_pool({"thread-worker-0": worker})

    await pool.shutdown()

    assert worker.cancel_event.is_set(), (
        "cancel_event must be set on busy workers during shutdown so the dying "
        "stream is classified as a cooperative cancel, not the spurious "
        "'unexpected cancellation' RuntimeError"
    )


@pytest.mark.asyncio
async def test_shutdown_does_not_set_cancel_event_for_idle_worker() -> None:
    """Idle workers have no in-flight stream to unwind — leave cancel_event alone."""
    worker = _live_busy_worker()
    worker.current_request_id = None
    worker.current_loop_id = None
    worker.status = WorkerThreadStatus.IDLE
    pool = _make_pool({"thread-worker-0": worker})

    await pool.shutdown()

    assert not worker.cancel_event.is_set()


@pytest.mark.asyncio
async def test_shutdown_skips_workers_already_cancel_event_set() -> None:
    """If cancel_event was already set (e.g. concurrent client cancel), do not
    re-set or double-log."""
    worker = _live_busy_worker()
    worker.cancel_event.set()
    pool = _make_pool({"thread-worker-0": worker})

    # Should not raise and should remain set (idempotent).
    await pool.shutdown()

    assert worker.cancel_event.is_set()


@pytest.mark.asyncio
async def test_shutdown_sentinel_still_enqueued_after_cancel(caplog) -> None:
    """The None shutdown sentinel is still put on the queue for the worker to
    consume after its in-flight request unwinds."""
    worker = _live_busy_worker()
    pool = _make_pool({"thread-worker-0": worker})

    await pool.shutdown()

    # request_queue.put should have been called with None (the sentinel).
    puts = [call.args[0] for call in worker.request_queue.put.call_args_list]
    assert None in puts
