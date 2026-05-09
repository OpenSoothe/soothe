"""Unit tests for PoolLoopRunner and WorkerPool (RFC-221 enhancement).

Mocks multiprocessing components so no real subprocess is spawned.
"""

from __future__ import annotations

import asyncio
import queue
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from soothe.config import SootheConfig
from soothe.config.daemon_config import WorkerPoolConfig
from soothe.core.runner.pool_runner import (
    PoolLoopRunner,
    PoolMetrics,
    WorkerPool,
    WorkerProcess,
    WorkerStatus,
)
from soothe.protocols.runner import LoopRunRequest


def _make_request(**kwargs: Any) -> LoopRunRequest:
    defaults: dict[str, Any] = dict(
        loop_id="loop-1",
        thread_id="thread-1",
        user_input="hello",
    )
    defaults.update(kwargs)
    return LoopRunRequest(**defaults)


def _make_config() -> SootheConfig:
    return SootheConfig()


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
            worker_id="worker-0",
        )

        worker.mark_busy("loop-456", "req-456")

        assert worker.status == WorkerStatus.BUSY
        assert worker.current_loop_id == "loop-456"


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
        config = _make_config()

        # Clear any existing singleton
        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        # Mock multiprocessing context
        mock_ctx = MagicMock()
        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = True
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        with patch("multiprocessing.get_context", return_value=mock_ctx):
            pool = await WorkerPool.get_shared_instance(config)

        assert pool is not None
        assert WorkerPool._shared_pool is pool

        # Cleanup
        await WorkerPool.close_shared_instance()
        assert WorkerPool._shared_pool is None

    @pytest.mark.asyncio
    async def test_close_shared_instance_destroys_pool(self) -> None:
        """close_shared_instance() destroys singleton."""
        config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        mock_ctx = MagicMock()
        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = False  # Already dead for clean shutdown
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        with patch("multiprocessing.get_context", return_value=mock_ctx):
            await WorkerPool.get_shared_instance(config)

        # Now close
        await WorkerPool.close_shared_instance()

        assert WorkerPool._shared_pool is None

    @pytest.mark.asyncio
    async def test_submit_yields_chunks_from_worker(self) -> None:
        """submit() dispatches to worker and yields chunks."""
        config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        # Create mock worker with pre-filled result queue
        # Format: (msg_type, request_id, payload) - 3-tuple for _poll_worker_responses
        chunk1 = (("ns",), "messages", "hello")
        chunk2 = (("ns",), "messages", "world")
        fixed_request_id = "abcd1234efgh5678"

        result_q: queue.Queue[tuple[str, str, Any]] = queue.Queue()
        result_q.put(("chunk", fixed_request_id, chunk1))
        result_q.put(("chunk", fixed_request_id, chunk2))
        result_q.put(("done", fixed_request_id, None))

        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_process.is_alive.return_value = True

        request_q = MagicMock()
        request_q.put = MagicMock()  # Captures dispatched request

        worker = WorkerProcess(
            process=mock_process,
            request_queue=request_q,
            response_queue=result_q,
            worker_id="worker-0",
            status=WorkerStatus.IDLE,
        )

        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        fake_uuid = SimpleNamespace(hex=fixed_request_id + fixed_request_id)

        with (
            patch("multiprocessing.get_context", return_value=mock_ctx),
            patch("soothe.core.runner.pool_runner.uuid.uuid4", return_value=fake_uuid),
        ):
            pool = await WorkerPool.get_shared_instance(config)
            pool._workers = {"worker-0": worker}

            request = _make_request()
            result = []
            async for chunk in pool.submit(request):
                result.append(chunk)

        assert result == [chunk1, chunk2]
        request_q.put.assert_called_once()

        await WorkerPool.close_shared_instance()

    @pytest.mark.asyncio
    async def test_submit_early_close_drains_remaining_chunks(self) -> None:
        """Consumer disconnect before done: background drain absorbs rest; worker becomes idle."""
        config = _make_config()

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
            worker_id="worker-0",
            status=WorkerStatus.IDLE,
        )

        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        fake_uuid = SimpleNamespace(hex=fixed_request_id + fixed_request_id)

        with (
            patch("multiprocessing.get_context", return_value=mock_ctx),
            patch("soothe.core.runner.pool_runner.uuid.uuid4", return_value=fake_uuid),
        ):
            pool = await WorkerPool.get_shared_instance(config)
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
    async def test_submit_raises_on_worker_error(self) -> None:
        """submit() re-raises error from worker."""
        config = _make_config()

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
            worker_id="worker-0",
            status=WorkerStatus.IDLE,
        )

        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        fake_uuid = SimpleNamespace(hex=fixed_request_id + fixed_request_id)

        with (
            patch("multiprocessing.get_context", return_value=mock_ctx),
            patch("soothe.core.runner.pool_runner.uuid.uuid4", return_value=fake_uuid),
        ):
            pool = await WorkerPool.get_shared_instance(config)
            pool._workers = {"worker-0": worker}

            with pytest.raises(ValueError, match="worker boom"):
                async for _ in pool.submit(_make_request()):
                    pass

        await WorkerPool.close_shared_instance()

    @pytest.mark.asyncio
    async def test_get_metrics_returns_pool_stats(self) -> None:
        """get_metrics() returns pool utilization stats."""
        config = _make_config()

        WorkerPool._shared_pool = None
        WorkerPool._pool_lock = None

        mock_ctx = MagicMock()
        mock_process = MagicMock()
        mock_process.is_alive.return_value = True
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        with patch("multiprocessing.get_context", return_value=mock_ctx):
            pool = await WorkerPool.get_shared_instance(config)

            # Create some workers with different statuses
            empty_rq = MagicMock()
            empty_rq.get_nowait.side_effect = queue.Empty
            pool._workers = {
                "worker-0": WorkerProcess(
                    process=mock_process,
                    request_queue=MagicMock(),
                    response_queue=empty_rq,
                    worker_id="worker-0",
                    status=WorkerStatus.IDLE,
                    requests_completed=5,
                ),
                "worker-1": WorkerProcess(
                    process=mock_process,
                    request_queue=MagicMock(),
                    response_queue=empty_rq,
                    worker_id="worker-1",
                    status=WorkerStatus.BUSY,
                    requests_completed=3,
                ),
            }

            metrics = pool.get_metrics()

        assert metrics.total_workers == 4  # pool_size from config
        assert metrics.idle_workers == 1
        assert metrics.busy_workers == 1
        assert metrics.total_requests_completed == 0  # pool-level counter, not per-worker

        await WorkerPool.close_shared_instance()


class TestPoolLoopRunner:
    """PoolLoopRunner implements LoopRunnerProtocol."""

    @pytest.mark.asyncio
    async def test_run_delegates_to_pool(self) -> None:
        """run() delegates to WorkerPool.submit()."""
        config = _make_config()

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
            worker_id="worker-0",
            status=WorkerStatus.IDLE,
        )

        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = mock_process
        mock_ctx.Queue.side_effect = queue.Queue

        fake_uuid = SimpleNamespace(hex=fixed_request_id + fixed_request_id)

        with (
            patch("multiprocessing.get_context", return_value=mock_ctx),
            patch("soothe.core.runner.pool_runner.uuid.uuid4", return_value=fake_uuid),
        ):
            pool = await WorkerPool.get_shared_instance(config)
            pool._workers = {"worker-0": worker}

            runner = PoolLoopRunner("loop-1", config)
            request = _make_request(loop_id="loop-1")

            result = []
            async for chunk in runner.run(request):
                result.append(chunk)

        assert result == [chunk1]

        await WorkerPool.close_shared_instance()

    @pytest.mark.asyncio
    async def test_cancel_calls_pool_cancel_request(self) -> None:
        """cancel() delegates to WorkerPool.cancel_request()."""
        config = _make_config()

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
            pool = await WorkerPool.get_shared_instance(config)
            pool._workers = {
                "worker-0": WorkerProcess(
                    process=mock_process,
                    request_queue=MagicMock(),
                    response_queue=empty_rq,
                    worker_id="worker-0",
                    status=WorkerStatus.IDLE,
                )
            }

            runner = PoolLoopRunner("loop-1", config)
            runner._pool = pool

            await runner.cancel()

        await WorkerPool.close_shared_instance()


class TestWorkerPoolConfig:
    """WorkerPoolConfig defaults and validation."""

    def test_defaults(self) -> None:
        """Default configuration values."""
        cfg = WorkerPoolConfig()
        assert cfg.enabled is True
        assert cfg.pool_size == 4
        assert cfg.idle_timeout_seconds == 300
        assert cfg.max_requests_per_worker == 100

    def test_pool_size_bounds(self) -> None:
        """pool_size must be 1-128."""
        # Valid
        WorkerPoolConfig(pool_size=1)
        WorkerPoolConfig(pool_size=128)

        # Invalid
        with pytest.raises(Exception):  # Pydantic ValidationError
            WorkerPoolConfig(pool_size=0)
        with pytest.raises(Exception):
            WorkerPoolConfig(pool_size=129)
