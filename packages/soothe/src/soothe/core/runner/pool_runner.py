"""Persistent worker pool for loop execution (RFC-221 enhancement).

Pre-warms N worker processes at daemon startup to eliminate ~8s per-query
overhead. Workers create fresh SootheRunner instances per request (Option A)
ensuring no user data leakage across requests.

ARCHITECTURE: Each worker has TWO queues created at spawn time (inherited):
    - request_queue: main process → worker (dispatch requests)
    - response_queue: worker → main process (stream responses)

This avoids the multiprocessing limitation that Queue objects cannot be
pickled and sent through other Queue objects - they must be inherited at
process spawn time.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import multiprocessing.context
import queue
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from soothe.config.settings import SootheConfig
from soothe.protocols.runner import LoopRunnerProtocol, LoopRunRequest

if TYPE_CHECKING:
    from soothe.core.runner._runner_shared import StreamChunk

logger = logging.getLogger(__name__)


class WorkerStatus(StrEnum):
    """Worker process status."""

    IDLE = "idle"
    BUSY = "busy"
    SHUTTING_DOWN = "shutting_down"
    DEAD = "dead"


@dataclass
class WorkerProcess:
    """State for a single worker process in the pool."""

    process: multiprocessing.Process
    request_queue: multiprocessing.Queue  # main → worker
    response_queue: multiprocessing.Queue  # worker → main
    worker_id: str
    status: WorkerStatus = WorkerStatus.IDLE
    current_loop_id: str | None = None
    current_request_id: str | None = None
    requests_completed: int = 0
    started_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)

    def is_alive(self) -> bool:
        """Check if the process is still running."""
        return self.process.is_alive()

    def mark_idle(self) -> None:
        """Mark worker as idle after request completion."""
        self.status = WorkerStatus.IDLE
        self.current_loop_id = None
        self.current_request_id = None
        self.last_activity = datetime.now()

    def mark_busy(self, loop_id: str, request_id: str) -> None:
        """Mark worker as busy handling a request."""
        self.status = WorkerStatus.BUSY
        self.current_loop_id = loop_id
        self.current_request_id = request_id
        self.last_activity = datetime.now()


@dataclass
class PoolMetrics:
    """Pool utilization and performance metrics."""

    total_workers: int
    idle_workers: int
    busy_workers: int
    dead_workers: int
    total_requests_completed: int
    requests_in_progress: int
    avg_request_latency_ms: float = 0.0
    worker_uptimes: dict[str, float] = field(default_factory=dict)


def _spawn_safe_config(config: SootheConfig | None) -> SootheConfig:
    """Return a copy of config safe for multiprocessing spawn pickling.

    Same as local_runner._spawn_safe_config — strips runtime caches.
    """
    from soothe.core.runner.local_runner import _spawn_safe_config as _local_spawn_safe_config

    return _local_spawn_safe_config(config)


def _pool_worker(
    config: SootheConfig,
    worker_id: str,
    request_queue: multiprocessing.Queue,
    response_queue: multiprocessing.Queue,
    idle_timeout_seconds: int,
    max_requests: int,
) -> None:
    """Persistent worker process main loop.

    Top-level function (picklable) that runs indefinitely:
        - Wait for requests on request_queue (with idle timeout)
        - Create fresh SootheRunner per request (no user data leakage)
        - Execute request, stream results to response_queue
        - Exit on shutdown sentinel, idle timeout, or max requests

    Args:
        config: Spawn-safe SootheConfig.
        worker_id: Unique worker identifier for logging.
        request_queue: Queue for receiving requests from main process.
        response_queue: Queue for sending responses to main process.
        idle_timeout_seconds: Exit after this many seconds idle.
        max_requests: Exit after this many requests completed.
    """
    import asyncio as _asyncio

    from soothe.core.runner import SootheRunner
    from soothe.core.runner.worker_logging import configure_loop_runner_worker_logging

    loop = _asyncio.new_event_loop()
    _asyncio.set_event_loop(loop)

    requests_completed = 0

    def _run_single(req: LoopRunRequest, request_id: str) -> None:
        """Execute one request with fresh SootheRunner."""
        configure_loop_runner_worker_logging(config, req.loop_id)

        async def _execute() -> None:
            runner = SootheRunner(config)
            try:
                async for chunk in runner.astream(
                    req.user_input,
                    thread_id=req.thread_id,
                    workspace=req.workspace,
                    autonomous=req.autonomous,
                    max_iterations=req.max_iterations,
                    preferred_subagent=req.preferred_subagent,
                ):
                    # Tag response with request_id for routing
                    response_queue.put(("chunk", request_id, chunk))
                response_queue.put(("done", request_id, None))
            except Exception as exc:
                response_queue.put(("error", request_id, exc))

        loop.run_until_complete(_execute())

    while requests_completed < max_requests:
        try:
            msg = request_queue.get(timeout=idle_timeout_seconds)
        except queue.Empty:
            logger.info("Worker %s idle timeout (%ds), exiting", worker_id, idle_timeout_seconds)
            break

        if msg is None:
            # Shutdown sentinel
            logger.info("Worker %s received shutdown signal, exiting", worker_id)
            break

        # Parse message: ("request", request_id, LoopRunRequest)
        msg_type, request_id, req = msg
        if msg_type != "request":
            logger.warning("Worker %s received unexpected message type: %s", worker_id, msg_type)
            continue

        logger.debug(
            "Worker %s starting request for loop=%s request_id=%s",
            worker_id,
            req.loop_id,
            request_id,
        )
        _run_single(req, request_id)
        requests_completed += 1
        logger.debug(
            "Worker %s completed request %d/%d for loop=%s request_id=%s",
            worker_id,
            requests_completed,
            max_requests,
            req.loop_id,
            request_id,
        )

    loop.close()
    logger.info("Worker %s exiting after %d requests", worker_id, requests_completed)


class WorkerPool:
    """Singleton pool of persistent worker processes for loop execution.

    Pre-warms N worker processes at daemon startup. Each worker has two queues:
        - request_queue: main process sends requests
        - response_queue: worker sends responses back

    Workers execute requests with fresh SootheRunner instances and stream
    results tagged with request_id for routing to the correct pending request.

    Architecture:
        Daemon → LoopRunnerFactory → WorkerPool (singleton)
                                         ↓
        WorkerProcess[0..N]
            ← request_queue (dispatch requests)
            → response_queue (stream responses)

    Lifecycle:
        - Startup: pre-warm N workers (configurable)
        - Runtime: workers pull requests, execute, return to pool
        - Shutdown: signal all workers to exit, wait, then force-kill
    """

    _shared_pool: WorkerPool | None = None
    _pool_lock: asyncio.Lock | None = None

    def __init__(
        self,
        config: SootheConfig,
        pool_size: int = 4,
        idle_timeout_seconds: int = 300,
        max_requests_per_worker: int = 100,
    ) -> None:
        self._config = config
        self._pool_size = pool_size
        self._idle_timeout_seconds = idle_timeout_seconds
        self._max_requests_per_worker = max_requests_per_worker

        self._ctx = multiprocessing.get_context("spawn")
        self._workers: dict[str, WorkerProcess] = {}
        self._workers_by_loop_id: dict[str, str] = {}  # loop_id -> worker_id
        self._dispatch_semaphore: asyncio.Semaphore | None = None
        self._running = False
        self._metrics_requests_total = 0
        self._metrics_latencies: list[float] = []
        # Track pending responses by request_id
        self._pending_responses: dict[str, asyncio.Queue] = {}
        # Background task to poll worker response queues
        self._poll_task: asyncio.Task | None = None

    @classmethod
    async def get_shared_instance(cls, config: SootheConfig) -> WorkerPool:
        """Get or create the singleton pool instance."""
        if cls._shared_pool is not None:
            return cls._shared_pool

        if cls._pool_lock is None:
            cls._pool_lock = asyncio.Lock()

        async with cls._pool_lock:
            if cls._shared_pool is not None:
                return cls._shared_pool

            pool_config = config.daemon.worker_pool
            pool = WorkerPool(
                config=config,
                pool_size=pool_config.pool_size,
                idle_timeout_seconds=pool_config.idle_timeout_seconds,
                max_requests_per_worker=pool_config.max_requests_per_worker,
            )
            await pool.start()
            cls._shared_pool = pool
            return pool

    @classmethod
    async def close_shared_instance(cls) -> None:
        """Close and destroy the singleton pool instance."""
        if cls._shared_pool is None:
            return

        if cls._pool_lock is None:
            cls._pool_lock = asyncio.Lock()

        async with cls._pool_lock:
            if cls._shared_pool is None:
                return

            await cls._shared_pool.shutdown()
            cls._shared_pool = None

    async def start(self) -> None:
        """Pre-warm all worker processes."""
        self._dispatch_semaphore = asyncio.Semaphore(self._pool_size)
        spawn_config = _spawn_safe_config(self._config)

        for i in range(self._pool_size):
            worker_id = f"worker-{i}"
            await self._spawn_worker(worker_id, spawn_config)

        self._running = True
        # Start background poll task to route responses
        self._poll_task = asyncio.create_task(self._poll_worker_responses())

        logger.info(
            "WorkerPool: pre-warmed %d workers (idle_timeout=%ds, max_requests=%d)",
            self._pool_size,
            self._idle_timeout_seconds,
            self._max_requests_per_worker,
        )

    async def _spawn_worker(self, worker_id: str, config: SootheConfig) -> WorkerProcess:
        """Spawn a single worker process with two queues."""
        # Create both queues at spawn time (inherited by worker)
        request_queue: Any = self._ctx.Queue()
        response_queue: Any = self._ctx.Queue()

        process = self._ctx.Process(
            target=_pool_worker,
            args=(
                config,
                worker_id,
                request_queue,
                response_queue,
                self._idle_timeout_seconds,
                self._max_requests_per_worker,
            ),
            daemon=True,
            name=worker_id,
        )
        process.start()

        worker = WorkerProcess(
            process=process,
            request_queue=request_queue,
            response_queue=response_queue,
            worker_id=worker_id,
            started_at=datetime.now(),
        )
        self._workers[worker_id] = worker

        logger.debug("WorkerPool: spawned worker %s (pid=%d)", worker_id, process.pid)
        return worker

    async def _poll_worker_responses(self) -> None:
        """Background task: poll worker response queues and route to pending requests."""
        loop = asyncio.get_event_loop()

        while self._running:
            for worker_id, worker in list(self._workers.items()):
                if not worker.is_alive():
                    continue
                if worker.current_request_id is None:
                    # Check for stale responses (from crashed worker)
                    try:
                        msg = await loop.run_in_executor(
                            None,
                            lambda: worker.response_queue.get_nowait(),
                        )
                        logger.warning(
                            "WorkerPool: orphan response from idle worker %s: %s",
                            worker_id,
                            msg[0],
                        )
                    except queue.Empty:
                        pass
                    continue

                try:
                    # Non-blocking get from response queue
                    msg = await loop.run_in_executor(
                        None,
                        lambda: worker.response_queue.get_nowait(),
                    )
                except queue.Empty:
                    continue

                # Parse: (msg_type, request_id, payload)
                msg_type, request_id, payload = msg

                # Route to pending response queue
                response_queue = self._pending_responses.get(request_id)
                if response_queue is not None:
                    await response_queue.put((msg_type, payload))
                else:
                    logger.warning(
                        "WorkerPool: orphan response for unknown request_id=%s",
                        request_id,
                    )

            # Short sleep to avoid busy polling
            await asyncio.sleep(0.05)

    async def _respawn_worker(self, dead_worker: WorkerProcess) -> None:
        """Replace a dead worker with a fresh one."""
        logger.warning("WorkerPool: respawning dead worker %s", dead_worker.worker_id)

        # Clean up dead process
        if dead_worker.process.is_alive():
            dead_worker.process.terminate()
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: dead_worker.process.join(timeout=5)
            )

        # Spawn replacement
        spawn_config = _spawn_safe_config(self._config)
        new_worker = await self._spawn_worker(dead_worker.worker_id, spawn_config)
        self._workers[dead_worker.worker_id] = new_worker

    async def submit(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Submit request to pool, await available worker, stream results."""
        # Generate unique request_id for this request
        request_id = uuid.uuid4().hex[:16]

        # Wait for available worker slot
        async with self._dispatch_semaphore:
            # Find an idle worker
            worker = None
            for w in self._workers.values():
                if w.status == WorkerStatus.IDLE and w.is_alive():
                    worker = w
                    break

            # If no idle worker, respawn a dead one or wait
            if worker is None:
                for w in self._workers.values():
                    if w.status == WorkerStatus.DEAD or not w.is_alive():
                        await self._respawn_worker(w)
                        worker = self._workers[w.worker_id]
                        break

            if worker is None:
                raise RuntimeError("No available workers in pool")

        # Create response queue for this request (asyncio.Queue for intra-process routing)
        response_queue: asyncio.Queue = asyncio.Queue()
        self._pending_responses[request_id] = response_queue

        # Track loop_id -> worker_id for cancellation
        self._workers_by_loop_id[request.loop_id] = worker.worker_id
        worker.mark_busy(request.loop_id, request_id)

        # Dispatch to worker: ("request", request_id, LoopRunRequest)
        worker.request_queue.put(("request", request_id, request))

        start_time = datetime.now()

        try:
            while True:
                msg_type, payload = await response_queue.get()

                if msg_type == "done":
                    worker.mark_idle()
                    self._workers_by_loop_id.pop(request.loop_id, None)
                    self._pending_responses.pop(request_id, None)
                    self._metrics_requests_total += 1
                    latency_ms = (datetime.now() - start_time).total_seconds() * 1000
                    self._metrics_latencies.append(latency_ms)
                    worker.requests_completed += 1
                    return
                if msg_type == "error":
                    worker.mark_idle()
                    self._workers_by_loop_id.pop(request.loop_id, None)
                    self._pending_responses.pop(request_id, None)
                    raise payload

                # msg_type == "chunk"
                yield payload
        except asyncio.CancelledError:
            logger.info("Pool request %s cancelled by client disconnect", request_id)
            raise
        finally:
            worker.mark_idle()
            self._workers_by_loop_id.pop(request.loop_id, None)
            self._pending_responses.pop(request_id, None)

    async def cancel_request(self, loop_id: str) -> None:
        """Signal cancellation to worker handling this loop_id.

        NOTE: Cooperative cancellation is not yet implemented for pool mode.
        This method logs the intent but does not interrupt the worker.
        """
        worker_id = self._workers_by_loop_id.get(loop_id)
        if worker_id is None:
            logger.debug("WorkerPool: no active request for loop_id=%s", loop_id)
            return

        logger.info(
            "WorkerPool: cancellation requested for loop_id=%s on worker=%s (not implemented)",
            loop_id,
            worker_id,
        )

    async def shutdown(self) -> None:
        """Graceful shutdown: signal workers, wait, then force-kill."""
        self._running = False

        # Stop poll task
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        logger.info("WorkerPool: shutting down %d workers", len(self._workers))

        loop = asyncio.get_event_loop()

        # Send shutdown sentinel to all workers
        for worker in self._workers.values():
            if worker.is_alive():
                worker.request_queue.put(None)
                worker.status = WorkerStatus.SHUTTING_DOWN

        # Wait for graceful exit
        for worker in self._workers.values():
            if worker.process.is_alive():
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: worker.process.join(timeout=5)),
                        timeout=10,
                    )
                except TimeoutError:
                    logger.warning(
                        "WorkerPool: worker %s did not exit gracefully, terminating",
                        worker.worker_id,
                    )
                    worker.process.terminate()

        # Force kill any remaining
        for worker in self._workers.values():
            if worker.process.is_alive():
                logger.warning("WorkerPool: killing worker %s", worker.worker_id)
                worker.process.kill()
                worker.process.join(timeout=2)

        self._workers.clear()
        self._workers_by_loop_id.clear()
        self._pending_responses.clear()
        logger.info("WorkerPool: shutdown complete")

    def get_metrics(self) -> PoolMetrics:
        """Return pool utilization and performance metrics."""
        idle = sum(1 for w in self._workers.values() if w.status == WorkerStatus.IDLE)
        busy = sum(1 for w in self._workers.values() if w.status == WorkerStatus.BUSY)
        dead = sum(1 for w in self._workers.values() if not w.is_alive())

        uptimes = {
            w.worker_id: (datetime.now() - w.started_at).total_seconds()
            for w in self._workers.values()
        }

        avg_latency = 0.0
        if self._metrics_latencies:
            avg_latency = sum(self._metrics_latencies[-100:]) / len(self._metrics_latencies[-100:])

        return PoolMetrics(
            total_workers=self._pool_size,
            idle_workers=idle,
            busy_workers=busy,
            dead_workers=dead,
            total_requests_completed=self._metrics_requests_total,
            requests_in_progress=busy,
            avg_request_latency_ms=avg_latency,
            worker_uptimes=uptimes,
        )


class PoolLoopRunner:
    """Runs agent loops using the persistent worker pool.

    Implements LoopRunnerProtocol for integration with QueryEngine.
    One instance per loop_id, created by LoopRunnerFactory.
    """

    def __init__(self, loop_id: str, config: SootheConfig) -> None:
        self._loop_id = loop_id
        self._config = config
        self._pool: WorkerPool | None = None

    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Delegate to shared pool, stream results."""
        pool = await WorkerPool.get_shared_instance(self._config)
        self._pool = pool

        async for chunk in pool.submit(request):
            yield chunk

    async def cancel(self) -> None:
        """Request cancellation."""
        if self._pool is not None:
            await self._pool.cancel_request(self._loop_id)


# Verify structural compliance at import time (no overhead at runtime).
def _assert_protocol() -> None:
    _: LoopRunnerProtocol = PoolLoopRunner.__new__(PoolLoopRunner)  # type: ignore[assignment]


__all__ = [
    "WorkerPool",
    "WorkerProcess",
    "WorkerStatus",
    "PoolLoopRunner",
    "PoolMetrics",
    "_pool_worker",
]