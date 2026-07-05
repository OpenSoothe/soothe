"""Unit tests for PoolLoopRunner and WorkerPool (RFC-221 enhancement).

Mocks multiprocessing components so no real subprocess is spawned.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe.config import SootheConfig
from soothe.protocols.runner import LoopRunRequest

import soothe_daemon.runner.pool_runner as pool_runner_module
from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.config.models import WorkerPoolConfig
from soothe_daemon.runner.pool_runner import (
    PoolLoopRunner,
    PoolMetrics,
    WorkerPool,
    WorkerProcess,
    WorkerStatus,
    _start_thread_heartbeat,
)


def _make_request(**kwargs: Any) -> LoopRunRequest:
    defaults: dict[str, Any] = dict(
        loop_id="loop-1",
        thread_id="thread-1",
        user_input="hello",
    )
    defaults.update(kwargs)
    return LoopRunRequest(**defaults)


def _make_config() -> tuple[SootheDaemonConfig, SootheConfig]:
    return SootheDaemonConfig(), SootheConfig()


def _make_cancel_event() -> multiprocessing.Event:
    """Create a mock cancel_event for tests."""
    ctx = multiprocessing.get_context("spawn")
    return ctx.Event()


def _mock_mp_spawn_context() -> MagicMock:
    """Multiprocessing spawn context mock that completes worker warmup on start()."""
    mock_ctx = MagicMock()

    def _process_factory(*_args: Any, **kwargs: Any) -> MagicMock:
        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = True
        process_args = kwargs.get("args") or (_args[1] if len(_args) > 1 else ())
        warmup_event = process_args[-1] if process_args else None

        def _start() -> None:
            if warmup_event is not None and hasattr(warmup_event, "set"):
                warmup_event.set()

        mock_process.start.side_effect = _start
        return mock_process

    mock_ctx.Process.side_effect = _process_factory
    mock_ctx.Queue.side_effect = queue.Queue
    mock_ctx.Event.side_effect = threading.Event
    return mock_ctx


@pytest.fixture(autouse=True)
def _complete_mock_pool_warmup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mocked worker processes never run _pool_worker_body; unblock pool.start()."""

    async def _wait(self: WorkerPool, events: list[Any]) -> None:
        for event in events:
            if hasattr(event, "set"):
                event.set()

    monkeypatch.setattr(WorkerPool, "_wait_for_worker_warmups", _wait)


class TestWorkerProcess:
    """WorkerProcess state management."""

    def test_mark_idle_sets_status(self) -> None:
        """mark_idle() sets status to IDLE and clears loop_id."""
        mock_process = MagicMock()
        mock_process.is_alive.return_value = True
        worker = WorkerProcess(
            process=mock_process,
            request_queue=MagicMock(),
            response_queue=MagicMock(),
            cancel_event=_make_cancel_event(),
            worker_id="worker-0",
        )
        worker.status = WorkerStatus.BUSY
        worker.current_loop_id = "loop-123"

        worker.mark_idle()

        assert worker.status == WorkerStatus.IDLE
        assert worker.current_loop_id is None

    def test_mark_busy_sets_status(self) -> None:
        """mark_busy() sets status to BUSY with loop_id."""
        mock_process = MagicMock()
        mock_process.is_alive.return_value = True
        worker = WorkerProcess(
            process=mock_process,
            request_queue=MagicMock(),
            response_queue=MagicMock(),
            cancel_event=_make_cancel_event(),
            worker_id="worker-0",
        )

        worker.mark_busy("loop-456", "req-456")

        assert worker.status == WorkerStatus.BUSY
        assert worker.current_loop_id == "loop-456"


def test_log_pool_worker_fatal_writes_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fatal worker hook appends to pool_worker_bootstrap.log under SOOTHE_HOME."""
    monkeypatch.setattr(pool_runner_module, "SOOTHE_HOME", tmp_path)
    pool_runner_module._log_pool_worker_fatal("worker-9", RuntimeError("boom"))
    logf = tmp_path / "logs" / "pool_worker_bootstrap.log"
    assert logf.is_file()
    body = logf.read_text(encoding="utf-8")
    assert "worker-9" in body
    assert "boom" in body


class TestPoolMetrics:
    """PoolMetrics dataclass."""

    def test_metrics_defaults(self) -> None:
        """Metrics with default values."""
        metrics = PoolMetrics(
            total_workers=4,
            idle_workers=2,
            busy_workers=1,
            dead_workers=1,
            total_requests_completed=10,
            requests_in_progress=1,
        )

        assert metrics.avg_request_latency_ms == 0.0
        assert metrics.worker_uptimes == {}


class TestWorkerPool:
    """WorkerPool singleton and dispatch logic."""

    @pytest.mark.asyncio
    async def test_get_shared_instance_creates_pool(self) -> None:
        """get_shared_instance() creates singleton pool on first call."""
        daemon_config, agent_config = _make_config()

        # Clear any existing singleton
        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        # Mock multiprocessing context
        mock_ctx = _mock_mp_spawn_context()

        with patch("multiprocessing.get_context", return_value=mock_ctx):
            pool = await WorkerPool.get_shared_instance(agent_config, daemon_config)

        assert pool is not None
        assert WorkerPool._shared_pool is pool

        # Cleanup
        await WorkerPool.close_shared_instance()
        assert WorkerPool._shared_pool is None

    @pytest.mark.asyncio
    async def test_close_shared_instance_destroys_pool(self) -> None:
        """close_shared_instance() destroys singleton."""
        daemon_config, agent_config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        mock_ctx = MagicMock()
        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = False  # Already dead for clean shutdown
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        with patch("multiprocessing.get_context", return_value=mock_ctx):
            await WorkerPool.get_shared_instance(agent_config, daemon_config)

        # Now close
        await WorkerPool.close_shared_instance()

        assert WorkerPool._shared_pool is None

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Bridge task timing race: mock worker response_queue not routed properly"
    )
    async def test_submit_yields_chunks_from_worker(self) -> None:
        """submit() dispatches to worker and yields chunks."""
        daemon_config, agent_config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        chunk1 = (("ns",), "messages", "hello")
        chunk2 = (("ns",), "messages", "world")
        fixed_request_id = "abcd1234efgh5678"

        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = True

        request_q = MagicMock()
        dispatched = threading.Event()

        def _on_put(*_a: Any, **_k: Any) -> None:
            dispatched.set()

        request_q.put.side_effect = _on_put

        worker = WorkerProcess(
            process=mock_process,
            request_queue=request_q,
            response_queue=MagicMock(),  # Bypassed - we deliver to asyncio queue directly
            cancel_event=_make_cancel_event(),
            worker_id="worker-0",
            status=WorkerStatus.IDLE,
        )

        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        fake_uuid = SimpleNamespace(hex=fixed_request_id + fixed_request_id)

        with (
            patch("multiprocessing.get_context", return_value=mock_ctx),
            patch("soothe_daemon.runner.pool_runner.uuid.uuid4", return_value=fake_uuid),
        ):
            pool = await WorkerPool.get_shared_instance(agent_config, daemon_config)
            pool._workers = {"worker-0": worker}
            # Cancel bridge task from spawn - test delivers directly to asyncio queue
            old_task = pool._bridge_tasks.pop("worker-0", None)
            if old_task:
                old_task.cancel()

            # Background task: wait for dispatch, then deliver responses
            async def _deliver_responses() -> None:
                # Wait for request dispatch
                for _ in range(100):
                    if dispatched.is_set():
                        break
                    await asyncio.sleep(0.01)
                # Extra delay to ensure pending_responses is registered
                await asyncio.sleep(0.02)
                pq = pool._pending_responses.get(fixed_request_id)
                if pq is not None:
                    await pq.put(("chunk", chunk1))
                    await pq.put(("chunk", chunk2))
                    await pq.put(("done", None))

            asyncio.create_task(_deliver_responses())

            request = _make_request()
            result = []
            async for chunk in pool.submit(request):
                result.append(chunk)

        assert result == [chunk1, chunk2]
        request_q.put.assert_called_once()

        await WorkerPool.close_shared_instance()

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Bridge task timing race: mock worker response_queue not routed properly"
    )
    async def test_submit_waits_when_pool_saturated(self) -> None:
        """At max_pool_size with all workers busy, submit waits until a worker idles."""
        daemon_config, agent_config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = True

        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        req_id16 = "abcd1234efgh5678"
        fake_uuid = SimpleNamespace(hex=req_id16 + req_id16)

        result_q1: queue.Queue[tuple[str, str, Any]] = queue.Queue()
        request_q1 = MagicMock()
        dispatched = asyncio.Event()

        def _on_put(*_a: Any, **_k: Any) -> None:
            dispatched.set()

        request_q1.put.side_effect = _on_put
        request_q2 = MagicMock()

        w1 = WorkerProcess(
            process=mock_process,
            request_queue=request_q1,
            response_queue=result_q1,
            cancel_event=_make_cancel_event(),
            worker_id="worker-0",
            status=WorkerStatus.BUSY,
        )
        w1.mark_busy("loop-a", "old-a")
        w2 = WorkerProcess(
            process=mock_process,
            request_queue=request_q2,
            response_queue=queue.Queue(),
            cancel_event=_make_cancel_event(),
            worker_id="worker-1",
            status=WorkerStatus.BUSY,
        )
        w2.mark_busy("loop-b", "old-b")

        with (
            patch("multiprocessing.get_context", return_value=mock_ctx),
            patch("soothe_daemon.runner.pool_runner.uuid.uuid4", return_value=fake_uuid),
        ):
            pool = await WorkerPool.get_shared_instance(agent_config, daemon_config)
            pool._workers = {"worker-0": w1, "worker-1": w2}
            pool._max_pool_size = 2

            async def _consume() -> list[Any]:
                out: list[Any] = []
                async for ch in pool.submit(_make_request(loop_id="loop-new")):
                    out.append(ch)
                return out

            task = asyncio.create_task(_consume())
            for _ in range(200):
                await asyncio.sleep(0.01)
                if pool._waiting_for_worker_slot == 1:
                    break
            else:
                pytest.fail("expected a blocked waiter while pool is saturated")

            await pool._mark_worker_idle_and_notify(w1)
            await asyncio.wait_for(dispatched.wait(), timeout=2.0)

            result_q1.put(("done", req_id16, None))
            chunks = await asyncio.wait_for(task, timeout=2.0)

        assert chunks == []
        request_q1.put.assert_called()

        await WorkerPool.close_shared_instance()

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Bridge task timing race: mock worker response_queue not routed properly"
    )
    async def test_submit_early_close_drains_remaining_chunks(self) -> None:
        """Consumer disconnect before done: background drain absorbs rest; worker becomes idle."""
        daemon_config, agent_config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        fixed_request_id = "abcd1234efgh5678"
        chunk1 = (("ns",), "messages", "first")
        chunk2 = (("ns",), "messages", "second")

        result_q: queue.Queue[tuple[str, Any]] = queue.Queue()
        result_q.put(("chunk", fixed_request_id, chunk1))
        result_q.put(("chunk", fixed_request_id, chunk2))
        result_q.put(("done", fixed_request_id, None))

        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = True
        request_q = MagicMock()

        worker = WorkerProcess(
            process=mock_process,
            request_queue=request_q,
            response_queue=result_q,
            cancel_event=_make_cancel_event(),
            worker_id="worker-0",
            status=WorkerStatus.IDLE,
        )

        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        fake_uuid = SimpleNamespace(hex=fixed_request_id + fixed_request_id)

        with (
            patch("multiprocessing.get_context", return_value=mock_ctx),
            patch("soothe_daemon.runner.pool_runner.uuid.uuid4", return_value=fake_uuid),
        ):
            pool = await WorkerPool.get_shared_instance(agent_config, daemon_config)
            pool._workers = {"worker-0": worker}

            seen: list[Any] = []
            async for chunk in pool.submit(_make_request()):
                seen.append(chunk)
                break

            assert seen == [chunk1]

            for _ in range(200):
                if (
                    worker.status == WorkerStatus.IDLE
                    and fixed_request_id not in pool._pending_responses
                ):
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("abandon drain did not finish")

            assert worker.status == WorkerStatus.IDLE
            assert fixed_request_id not in pool._pending_responses

        await WorkerPool.close_shared_instance()

    @pytest.mark.asyncio
    async def test_dead_busy_worker_delivers_error_to_waiter(self) -> None:
        """When the OS worker process dies mid-request, poll path unblocks submit with RuntimeError."""
        daemon_config, agent_config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        fixed_request_id = "abcd1234efgh5678"

        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = False

        request_q = MagicMock()
        worker = WorkerProcess(
            process=mock_process,
            request_queue=request_q,
            response_queue=queue.Queue(),
            cancel_event=_make_cancel_event(),
            worker_id="worker-0",
            status=WorkerStatus.BUSY,
        )
        worker.mark_busy("loop-1", fixed_request_id)

        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        with patch("multiprocessing.get_context", return_value=mock_ctx):
            pool = await WorkerPool.get_shared_instance(agent_config, daemon_config)
            pool._workers = {"worker-0": worker}

            pending: asyncio.Queue = asyncio.Queue()
            pool._pending_responses[fixed_request_id] = pending

            with patch.object(pool, "_respawn_worker", new_callable=AsyncMock):
                await pool._handle_dead_worker(worker)

            msg_type, payload = await asyncio.wait_for(pending.get(), timeout=2.0)
            assert msg_type == "error"
            assert isinstance(payload, RuntimeError)
            assert "subprocess exited unexpectedly" in str(payload).lower()

        await WorkerPool.close_shared_instance()

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Bridge task timing race: mock worker response_queue not routed properly"
    )
    async def test_submit_raises_on_worker_error(self) -> None:
        """submit() re-raises error from worker."""
        daemon_config, agent_config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        exc = ValueError("worker boom")
        fixed_request_id = "abcd1234efgh5678"

        result_q: queue.Queue[tuple[str, str, Any]] = queue.Queue()
        result_q.put(("error", fixed_request_id, exc))

        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = True

        request_q = MagicMock()
        worker = WorkerProcess(
            process=mock_process,
            request_queue=request_q,
            response_queue=result_q,
            cancel_event=_make_cancel_event(),
            worker_id="worker-0",
            status=WorkerStatus.IDLE,
        )

        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        fake_uuid = SimpleNamespace(hex=fixed_request_id + fixed_request_id)

        with (
            patch("multiprocessing.get_context", return_value=mock_ctx),
            patch("soothe_daemon.runner.pool_runner.uuid.uuid4", return_value=fake_uuid),
        ):
            pool = await WorkerPool.get_shared_instance(agent_config, daemon_config)
            pool._workers = {"worker-0": worker}

            with pytest.raises(ValueError, match="worker boom"):
                async for _ in pool.submit(_make_request()):
                    pass

        await WorkerPool.close_shared_instance()

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Bridge task timing race: mock worker response_queue not routed properly"
    )
    async def test_submit_retries_when_worker_dies_at_dispatch_handoff(self) -> None:
        """Idle-timeout exit vs acquire race: retry dispatch instead of failing the turn."""
        daemon_config, agent_config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        chunk1 = (("ns",), "messages", "handoff-ok")
        fixed_request_id = "abcd1234efgh5678"

        good_result_q: queue.Queue[tuple[str, str, Any]] = queue.Queue()
        good_result_q.put(("chunk", fixed_request_id, chunk1))
        good_result_q.put(("done", fixed_request_id, None))

        bad_process = MagicMock()
        bad_process.pid = 1111
        # Acquire (True), handoff check (False), then _try_acquire skips dead (False+).
        bad_process.is_alive.side_effect = [True, False] + [False] * 8

        good_process = MagicMock()
        good_process.pid = 2222
        good_process.is_alive.return_value = True

        bad_worker = WorkerProcess(
            process=bad_process,
            request_queue=MagicMock(),
            response_queue=MagicMock(),
            cancel_event=_make_cancel_event(),
            worker_id="worker-0",
            status=WorkerStatus.IDLE,
        )
        good_worker = WorkerProcess(
            process=good_process,
            request_queue=MagicMock(),
            response_queue=good_result_q,
            cancel_event=_make_cancel_event(),
            worker_id="worker-1",
            status=WorkerStatus.IDLE,
        )

        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = good_process
        mock_ctx.Queue.side_effect = queue.Queue

        fake_uuid = SimpleNamespace(hex=fixed_request_id + fixed_request_id)

        with (
            patch("multiprocessing.get_context", return_value=mock_ctx),
            patch("soothe_daemon.runner.pool_runner.uuid.uuid4", return_value=fake_uuid),
        ):
            pool = await WorkerPool.get_shared_instance(agent_config, daemon_config)
            pool._workers = {"worker-0": bad_worker, "worker-1": good_worker}

            with patch.object(pool, "_handle_dead_worker", new=AsyncMock()):
                chunks: list[Any] = []
                async for chunk in pool.submit(_make_request()):
                    chunks.append(chunk)

        assert chunks == [chunk1]
        assert bad_process.is_alive.call_count >= 2

        await WorkerPool.close_shared_instance()

    @pytest.mark.asyncio
    async def test_get_metrics_returns_pool_stats(self) -> None:
        """get_metrics() returns pool utilization stats."""
        daemon_config, agent_config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        mock_ctx = MagicMock()
        mock_process = MagicMock()
        mock_process.is_alive.return_value = True
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        with patch("multiprocessing.get_context", return_value=mock_ctx):
            pool = await WorkerPool.get_shared_instance(agent_config, daemon_config)

            # Create some workers with different statuses
            empty_rq = MagicMock()
            empty_rq.get_nowait.side_effect = queue.Empty
            pool._workers = {
                "worker-0": WorkerProcess(
                    process=mock_process,
                    request_queue=MagicMock(),
                    response_queue=empty_rq,
                    cancel_event=_make_cancel_event(),
                    worker_id="worker-0",
                    status=WorkerStatus.IDLE,
                    requests_completed=5,
                ),
                "worker-1": WorkerProcess(
                    process=mock_process,
                    request_queue=MagicMock(),
                    response_queue=empty_rq,
                    cancel_event=_make_cancel_event(),
                    worker_id="worker-1",
                    status=WorkerStatus.BUSY,
                    requests_completed=3,
                ),
            }

            metrics = pool.get_metrics()

        assert metrics.total_workers == 4  # max_pool_size from config
        assert metrics.idle_workers == 1
        assert metrics.busy_workers == 1
        assert metrics.total_requests_completed == 0  # pool-level counter, not per-worker
        assert metrics.dispatch_waiters_waiting == 0

        await WorkerPool.close_shared_instance()


class TestPoolLoopRunner:
    """PoolLoopRunner implements LoopRunnerProtocol."""

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Bridge task timing race: mock worker response_queue not routed properly"
    )
    async def test_run_delegates_to_pool(self) -> None:
        """run() delegates to WorkerPool.submit()."""
        daemon_config, agent_config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        chunk1 = (("ns",), "messages", "result")
        fixed_request_id = "abcd1234efgh5678"

        result_q: queue.Queue[tuple[str, str, Any]] = queue.Queue()
        result_q.put(("chunk", fixed_request_id, chunk1))
        result_q.put(("done", fixed_request_id, None))

        mock_process = MagicMock()
        mock_process.is_alive.return_value = True

        request_q = MagicMock()
        worker = WorkerProcess(
            process=mock_process,
            request_queue=request_q,
            response_queue=result_q,
            cancel_event=_make_cancel_event(),
            worker_id="worker-0",
            status=WorkerStatus.IDLE,
        )

        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        fake_uuid = SimpleNamespace(hex=fixed_request_id + fixed_request_id)

        with (
            patch("multiprocessing.get_context", return_value=mock_ctx),
            patch("soothe_daemon.runner.pool_runner.uuid.uuid4", return_value=fake_uuid),
        ):
            pool = await WorkerPool.get_shared_instance(agent_config, daemon_config)
            pool._workers = {"worker-0": worker}

            runner = PoolLoopRunner("loop-1", agent_config, daemon_config)
            request = _make_request(loop_id="loop-1")

            result = []
            async for chunk in runner.run(request):
                result.append(chunk)

        assert result == [chunk1]

        await WorkerPool.close_shared_instance()

    @pytest.mark.asyncio
    async def test_cancel_calls_pool_cancel_request(self) -> None:
        """cancel() delegates to WorkerPool.cancel_request()."""
        daemon_config, agent_config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        mock_ctx = MagicMock()
        mock_process = MagicMock()
        mock_process.is_alive.return_value = True
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        empty_rq = MagicMock()
        empty_rq.get_nowait.side_effect = queue.Empty

        with patch("multiprocessing.get_context", return_value=mock_ctx):
            pool = await WorkerPool.get_shared_instance(agent_config, daemon_config)
            pool._workers = {
                "worker-0": WorkerProcess(
                    process=mock_process,
                    request_queue=MagicMock(),
                    response_queue=empty_rq,
                    cancel_event=_make_cancel_event(),
                    worker_id="worker-0",
                    status=WorkerStatus.IDLE,
                )
            }

            runner = PoolLoopRunner("loop-1", agent_config, daemon_config)
            runner._pool = pool

            await runner.cancel()

        await WorkerPool.close_shared_instance()


class TestThreadHeartbeat:
    """Background-thread heartbeats while the worker event loop is blocked."""

    def test_thread_heartbeat_emits_during_interval(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        response_queue = ctx.Queue()
        stop_event = threading.Event()
        _start_thread_heartbeat(
            response_queue=response_queue,
            request_id="req-heartbeat",
            stop_event=stop_event,
            heartbeat_interval_seconds=0.05,
            start_time=time.monotonic(),
        )
        time.sleep(0.2)
        stop_event.set()
        messages: list[tuple] = []
        while not response_queue.empty():
            messages.append(response_queue.get_nowait())
        assert any(msg[0] == "heartbeat" and msg[1] == "req-heartbeat" for msg in messages)


class TestWorkerPoolConfig:
    """WorkerPoolConfig defaults and validation."""

    def test_defaults(self) -> None:
        """Default configuration values (thread_pool is default runner mode)."""
        cfg = WorkerPoolConfig()
        assert cfg.enabled is False  # Disabled by default; thread_pool is default
        assert cfg.min_pool_size == 2
        assert cfg.max_pool_size == 4
        assert cfg.idle_timeout_seconds == 300
        assert cfg.max_requests_per_worker == 100
        assert cfg.request_timeout_seconds == 0  # no default timeout

    def test_pool_size_bounds(self) -> None:
        """min_pool_size and max_pool_size bounds."""
        # Valid
        WorkerPoolConfig(min_pool_size=1, max_pool_size=64)
        WorkerPoolConfig(min_pool_size=2, max_pool_size=128)

        # Invalid: min out of bounds
        with pytest.raises(Exception):  # Pydantic ValidationError
            WorkerPoolConfig(min_pool_size=0)
        with pytest.raises(Exception):
            WorkerPoolConfig(min_pool_size=65)

        # Invalid: max out of bounds
        with pytest.raises(Exception):
            WorkerPoolConfig(max_pool_size=0)
        with pytest.raises(Exception):
            WorkerPoolConfig(max_pool_size=129)

    def test_get_effective_pool_size(self) -> None:
        """get_effective_pool_size() ensures max >= min."""
        cfg = WorkerPoolConfig(min_pool_size=4, max_pool_size=2)
        assert cfg.get_effective_pool_size() == 4  # max(min, max)
