"""Regression tests for cancel + queued goal lifecycle (IG-581)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.query.engine import AsyncCancelOrchestrator, QueryAdmission, QueryEngine
from soothe_daemon.runner.thread_runner import ThreadPool, WorkerThreadState, WorkerThreadStatus
from soothe_daemon.runtime.loop_broadcast_budget import LoopBroadcastBudget


def _daemon_factory(*, broadcasts: list[dict[str, Any]] | None = None) -> SimpleNamespace:
    async def _broadcast(msg: dict[str, Any]) -> None:
        if broadcasts is not None:
            broadcasts.append(msg)

    daemon_config = SootheDaemonConfig(max_concurrent_threads=100)

    return SimpleNamespace(
        _runner=SimpleNamespace(
            current_thread_id=None,
            set_current_thread_id=lambda _tid: None,
            touch_thread_activity_timestamp=AsyncMock(),
            create_persisted_thread=AsyncMock(),
        ),
        _runner_factory=SimpleNamespace(
            create_runner=lambda _key: None,
            get_shared_execution_pool=AsyncMock(return_value=None),
        ),
        _query_state_lock=asyncio.Lock(),
        _thread_registry=SimpleNamespace(
            get=lambda _tid: None,
            get_thread_loop=lambda _tid: "",
        ),
        _daemon_workspace=Path.cwd(),
        _thread_logger=SimpleNamespace(
            _thread_id="thread-1",
            log_user_input=lambda _text: None,
            log_assistant_response=lambda _text: None,
            log=lambda *_args, **_kwargs: None,
            flush=lambda: None,
        ),
        _config=SimpleNamespace(
            observability=SimpleNamespace(
                thread_logging_retention_days=7,
                thread_logging_max_size_mb=10,
            ),
            agent=SimpleNamespace(
                loop=SimpleNamespace(
                    output_streaming=SimpleNamespace(
                        adaptive_threshold_chars=500,
                        adaptive_block_chars=1024,
                        adaptive_block_interval_ms=250,
                        file_output_threshold_chars=0,
                        file_output_preview_chars=500,
                        file_output_dir=None,
                        streaming_interval_ms=300,
                        message_coalesce_enabled=True,
                        tool_batch_enabled=True,
                        tool_batch_interval_ms=200,
                        suppress_redundant_stream_tool_updates=True,
                        skip_redundant_tool_message_wire=False,
                    )
                )
            ),
        ),
        _daemon_config=daemon_config,
        _global_history=None,
        _active_threads={},
        _current_query_task=None,
        _active_stream_loop_ids=set(),
        _loops_with_active_query=set(),
        _loop_broadcast_budget=LoopBroadcastBudget(80),
        _broadcast=_broadcast,
        _session_manager=SimpleNamespace(
            claim_loop_ownership=lambda *_args, **_kwargs: None,
            release_loop_ownership=lambda *_args, **_kwargs: None,
            subscribe_loop=lambda *_args, **_kwargs: True,
            get_stream_delivery=lambda *_args, **_kwargs: "batch",
            await_loop_delivery_drained=AsyncMock(return_value=True),
            get_clients_for_loop=AsyncMock(return_value=[]),
            get_loop_subscription_id=AsyncMock(return_value=None),
        ),
        _message_router=SimpleNamespace(_send_complete=lambda *_args, **_kwargs: None),
        _persistence_manager=SimpleNamespace(
            get_loop_metadata=AsyncMock(return_value=None),
        ),
    )


@pytest.mark.asyncio
async def test_turn_generation_supersedes_stale_finally_ownership() -> None:
    """A successor admitted turn must invalidate prior ``_owns_turn`` checks."""
    engine = QueryEngine(_daemon_factory())

    _, gen1 = await engine._admit_query(effective_loop_id="loop-a", thread_id="thread-1")
    await engine._release_query_admission("loop-a")
    _, gen2 = await engine._admit_query(effective_loop_id="loop-a", thread_id="thread-1")

    assert gen2 > gen1
    assert engine._owns_turn("loop-a", gen1) is False
    assert engine._owns_turn("loop-a", gen2) is True


@pytest.mark.asyncio
async def test_await_loop_ready_waits_for_cancel_orchestrator() -> None:
    """Queued intake must block until the background cancel task completes."""
    daemon = _daemon_factory()
    engine = QueryEngine(daemon)
    engine._cancel_orchestrator = AsyncCancelOrchestrator(daemon, engine)
    gate = asyncio.Event()

    async def slow_cancel() -> None:
        await gate.wait()

    task = asyncio.create_task(slow_cancel())
    engine._cancel_orchestrator._active_cancel_tasks["loop-a"] = task

    ready = asyncio.create_task(engine.await_loop_ready_for_turn("loop-a"))
    await asyncio.sleep(0.05)
    assert not ready.done()

    gate.set()
    await asyncio.wait_for(ready, timeout=1.0)
    await task


@pytest.mark.asyncio
async def test_await_loop_ready_waits_for_pool_dispatchable() -> None:
    """Queued intake must block while a pool worker remains busy on the loop."""
    daemon = _daemon_factory()
    pool = ThreadPool.__new__(ThreadPool)
    pool._running = True
    pool._worker_available = asyncio.Condition()
    thread = MagicMock()
    thread.is_alive.return_value = True
    pool._workers = {
        "thread-worker-0": WorkerThreadState(
            thread=thread,
            request_queue=MagicMock(),
            response_queue=MagicMock(),
            cancel_event=MagicMock(),
            stop_event=MagicMock(),
            worker_id="thread-worker-0",
            status=WorkerThreadStatus.BUSY,
            current_loop_id="loop-a",
            current_request_id="req-1",
        )
    }
    pool._workers_by_loop_id = {"loop-a": "thread-worker-0"}

    daemon._runner_factory.get_shared_execution_pool = AsyncMock(return_value=pool)
    engine = QueryEngine(daemon)

    ready = asyncio.create_task(engine.await_loop_ready_for_turn("loop-a"))
    await asyncio.sleep(0.05)
    assert not ready.done()

    pool._workers["thread-worker-0"].status = WorkerThreadStatus.IDLE
    pool._workers_by_loop_id.pop("loop-a", None)
    async with pool._worker_available:
        pool._worker_available.notify_all()

    await asyncio.wait_for(ready, timeout=1.0)


@pytest.mark.asyncio
async def test_await_loop_ready_waits_for_active_query_admission() -> None:
    """Queued turns must wait until loop admission is released."""
    daemon = _daemon_factory()
    engine = QueryEngine(daemon)
    daemon._loops_with_active_query.add("loop-a")

    ready = asyncio.create_task(engine.await_loop_ready_for_turn("loop-a"))
    await asyncio.sleep(0.05)
    assert not ready.done()

    async with daemon._query_state_lock:
        daemon._loops_with_active_query.discard("loop-a")
    await asyncio.wait_for(ready, timeout=1.0)


def test_thread_pool_is_loop_busy_and_dispatchable_gate() -> None:
    """Same-loop dispatch must wait until the mapped worker returns idle."""
    pool = ThreadPool.__new__(ThreadPool)
    pool._running = True
    pool._worker_available = asyncio.Condition()
    thread = MagicMock()
    thread.is_alive.return_value = True
    pool._workers = {
        "thread-worker-0": WorkerThreadState(
            thread=thread,
            request_queue=MagicMock(),
            response_queue=MagicMock(),
            cancel_event=MagicMock(),
            stop_event=MagicMock(),
            worker_id="thread-worker-0",
            status=WorkerThreadStatus.BUSY,
            current_loop_id="loop-a",
            current_request_id="req-1",
        )
    }
    pool._workers_by_loop_id = {"loop-a": "thread-worker-0"}

    assert pool.is_loop_busy("loop-a") is True
    assert pool.is_loop_busy("loop-b") is False

    pool._workers["thread-worker-0"].status = WorkerThreadStatus.IDLE
    pool._workers_by_loop_id.pop("loop-a", None)

    assert pool.is_loop_busy("loop-a") is False


@pytest.mark.asyncio
async def test_admit_query_increments_turn_generation_per_loop() -> None:
    """Each admitted loop turn receives a monotonically increasing generation."""
    engine = QueryEngine(_daemon_factory())

    _, gen1 = await engine._admit_query(effective_loop_id="loop-a", thread_id="t1")
    await engine._release_query_admission("loop-a")
    _, gen2 = await engine._admit_query(effective_loop_id="loop-a", thread_id="t1")
    await engine._release_query_admission("loop-a")

    assert gen1 == 1
    assert gen2 == 2

    admission, gen3 = await engine._admit_query(effective_loop_id="loop-b", thread_id="t2")
    assert admission is QueryAdmission.ADMITTED
    assert gen3 == 1


@pytest.mark.asyncio
async def test_unregister_query_task_is_identity_scoped() -> None:
    """A superseded turn must not evict a successor that reused the thread_id."""
    daemon = _daemon_factory()
    engine = QueryEngine(daemon)

    async def _noop() -> None:
        return None

    predecessor = asyncio.create_task(_noop())
    successor = asyncio.create_task(_noop())
    await asyncio.gather(predecessor, successor)

    # Successor now owns the shared checkpoint thread_id registration.
    daemon._active_threads["thread-1"] = successor

    # Stale predecessor finally must be a no-op (identity mismatch).
    await engine._unregister_query_task("thread-1", predecessor)
    assert daemon._active_threads.get("thread-1") is successor

    # The owning turn clears its own registration.
    await engine._unregister_query_task("thread-1", successor)
    assert "thread-1" not in daemon._active_threads
