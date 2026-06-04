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
import math
import multiprocessing
import multiprocessing.context
import queue
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.config import SOOTHE_HOME
from soothe.config.settings import SootheConfig
from soothe.core.runner._worker_utils import parse_intent_hint
from soothe.protocols.runner import LoopRunnerProtocol, LoopRunRequest

from soothe_daemon.config import SootheDaemonConfig

if TYPE_CHECKING:
    from soothe.core.runner._runner_shared import StreamChunk

logger = logging.getLogger(__name__)


def _start_thread_heartbeat(
    *,
    response_queue: multiprocessing.Queue,
    request_id: str,
    stop_event: threading.Event,
    heartbeat_interval_seconds: float,
    start_time: float,
) -> threading.Thread:
    """Emit pool heartbeats from a daemon thread (survives event-loop blocking).

    ``asyncio`` heartbeats stop when sync code blocks the worker loop (e.g. embedding
    model download via ``Future.result()``). A thread timer keeps the parent from
    marking the worker stuck during long CPU/IO work.
    """

    def _heartbeat_loop() -> None:
        while not stop_event.wait(timeout=heartbeat_interval_seconds):
            try:
                response_queue.put(
                    (
                        "heartbeat",
                        request_id,
                        {"elapsed_seconds": time.monotonic() - start_time},
                    )
                )
            except Exception:
                logger.debug(
                    "Worker heartbeat enqueue failed for request_id=%s",
                    request_id,
                    exc_info=True,
                )

    thread = threading.Thread(
        target=_heartbeat_loop,
        name=f"pool-hb-{request_id[:8]}",
        daemon=True,
    )
    thread.start()
    return thread


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
    cancel_event: multiprocessing.Event  # cooperative cancellation signal (inherited at spawn)
    worker_id: str
    status: WorkerStatus = WorkerStatus.IDLE
    current_loop_id: str | None = None
    current_request_id: str | None = None
    requests_completed: int = 0
    started_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    last_heartbeat_at: datetime | None = None  # timestamp of last heartbeat received
    #: True after we pushed a synthetic error for an unexpected process exit (poll loop).
    dead_failure_routed: bool = False

    def is_alive(self) -> bool:
        """Check if the process is still running."""
        return self.process.is_alive()

    def mark_idle(self) -> None:
        """Mark worker as idle after request completion."""
        self.status = WorkerStatus.IDLE
        self.current_loop_id = None
        self.current_request_id = None
        self.last_activity = datetime.now()
        self.last_heartbeat_at = None

    def mark_busy(self, loop_id: str, request_id: str) -> None:
        """Mark worker as busy handling a request."""
        self.status = WorkerStatus.BUSY
        self.current_loop_id = loop_id
        self.current_request_id = request_id
        now = datetime.now()
        self.last_activity = now
        # Grace period until the worker's first heartbeat arrives (SootheRunner init).
        self.last_heartbeat_at = now


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
    #: Coroutines waiting for an idle worker while the pool is at capacity.
    dispatch_waiters_waiting: int = 0


# Upper bounds (exclusive) for dispatch handoff latency (ms), overflow = last bucket.
_DISPATCH_WAIT_MS_BINS: tuple[float, ...] = (
    1.0,
    2.0,
    5.0,
    10.0,
    25.0,
    50.0,
    100.0,
    250.0,
    500.0,
    1000.0,
    5000.0,
)

# Upper bounds (exclusive) for concurrent waiters snapshot (integer depths as float).
_WAITER_DEPTH_BINS: tuple[float, ...] = (2.0, 3.0, 4.0, 6.0, 8.0, 16.0, 32.0, 64.0)


def _hist_bin_label_ms(idx: int) -> str:
    if idx >= len(_DISPATCH_WAIT_MS_BINS):
        return f">={_DISPATCH_WAIT_MS_BINS[-1]:.0f}ms"
    upper = _DISPATCH_WAIT_MS_BINS[idx]
    if upper < 1:
        return f"<{upper:.2f}ms"
    return f"<{upper:.0f}ms"


def _hist_bin_label_waiters(idx: int) -> str:
    if idx >= len(_WAITER_DEPTH_BINS):
        return f">={_WAITER_DEPTH_BINS[-1]:.0f} waiting"
    upper = _WAITER_DEPTH_BINS[idx]
    return f"<{upper:.0f} waiting"


class _ScalarHistogram:
    """Fixed-bin histogram + Welford mean/variance (O(1) memory)."""

    __slots__ = ("_bin_upper", "_counts", "_n", "_mean", "_m2", "_min", "_max")

    def __init__(self, bin_upper: tuple[float, ...]) -> None:
        self._bin_upper = bin_upper
        self._counts = [0] * (len(bin_upper) + 1)
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0
        self._min = 0.0
        self._max = 0.0

    def reset(self) -> None:
        self._counts = [0] * (len(self._bin_upper) + 1)
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0
        self._min = 0.0
        self._max = 0.0

    @property
    def count(self) -> int:
        return self._n

    def observe(self, value: float) -> None:
        if value < 0:
            value = 0.0
        idx = 0
        for i, edge in enumerate(self._bin_upper):
            if value < edge:
                idx = i
                break
        else:
            idx = len(self._bin_upper)
        self._counts[idx] += 1

        self._n += 1
        if self._n == 1:
            self._min = value
            self._max = value
        else:
            self._min = min(self._min, value)
            self._max = max(self._max, value)

        delta = value - self._mean
        self._mean += delta / self._n
        delta2 = value - self._mean
        self._m2 += delta * delta2

    def variance(self) -> float:
        if self._n < 2:
            return 0.0
        return self._m2 / float(self._n - 1)

    def format_parts(self, *, bin_label: Callable[[int], str]) -> list[str]:
        n = self._n
        if n == 0:
            return []
        stdev = math.sqrt(self.variance())
        parts = [
            f"n={n}",
            f"mean={self._mean:.2f}",
            f"stdev={stdev:.2f}",
            f"min={self._min:.2f}",
            f"max={self._max:.2f}",
        ]
        for i, c in enumerate(self._counts):
            if c == 0:
                continue
            pct = 100.0 * c / n
            parts.append(f"{bin_label(idx=i)}={pct:.1f}%")
        return parts


class PoolDispatchWaitStatsCollector:
    """Histograms for time waiting for a worker and for queue-depth snapshots.

    Mirrors the EventBus wire-size stats pattern: fixed bins, periodic log emission.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._wait_ms = _ScalarHistogram(_DISPATCH_WAIT_MS_BINS)
        self._waiter_depth = _ScalarHistogram(_WAITER_DEPTH_BINS)
        self._max_waiters_peak = 0
        self._last_activity_mono = 0.0

    def _reset_windows(self) -> None:
        self._wait_ms.reset()
        self._waiter_depth.reset()
        self._max_waiters_peak = 0

    async def record_dispatch_handoff(self, wait_ms: float) -> None:
        """Record end-to-end time inside dispatch semaphore until worker is reserved."""
        async with self._lock:
            self._last_activity_mono = time.monotonic()
            self._wait_ms.observe(wait_ms)

    async def record_waiter_snapshot(self, depth: int) -> None:
        """Record how many coroutines were waiting (including this one) for a slot."""
        async with self._lock:
            self._last_activity_mono = time.monotonic()
            self._waiter_depth.observe(float(depth))
            if depth > self._max_waiters_peak:
                self._max_waiters_peak = depth

    async def emit_log_if_active(
        self,
        *,
        idle_pause_seconds: float,
        log_fn: Callable[[str], None],
    ) -> bool:
        """Emit one log line for the current window; idle windows are discarded."""
        now = time.monotonic()
        async with self._lock:
            if self._last_activity_mono == 0.0:
                return False
            if now - self._last_activity_mono >= idle_pause_seconds:
                self._reset_windows()
                return False
            if self._wait_ms.count == 0 and self._waiter_depth.count == 0:
                return False
            wait_parts = self._wait_ms.format_parts(bin_label=_hist_bin_label_ms)
            depth_parts = self._waiter_depth.format_parts(bin_label=_hist_bin_label_waiters)
            peak = self._max_waiters_peak
            self._reset_windows()
        parts = ["[pool_dispatch_stats]"]
        if wait_parts:
            parts.append("handoff_ms: " + " ".join(wait_parts))
        if depth_parts:
            parts.append("wait_queue_depth: " + " ".join(depth_parts))
        if peak > 0:
            parts.append(f"peak_waiters={peak}")
        line = " ".join(parts)
        log_fn(line)
        return True


def _spawn_safe_config(config: SootheConfig | None) -> SootheConfig:
    """Return a copy of config safe for multiprocessing spawn pickling.

    Same as _worker_utils.spawn_safe_config — strips runtime caches.
    """
    from soothe.core.runner._worker_utils import spawn_safe_config

    return spawn_safe_config(config)


def _log_pool_worker_fatal(worker_id: str, exc: BaseException) -> None:
    """Append uncaught subprocess errors to a file under ``SOOTHE_HOME/logs``.

    Worker file logging (``runner.log``) is only attached when a loop request
    starts, so import/bootstrap failures in an otherwise-idle pool worker would
    otherwise disappear unless stderr is captured.
    """
    import os
    import traceback

    base = Path(SOOTHE_HOME)
    log_path = base / "logs" / "pool_worker_bootstrap.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(
                f"\n--- {datetime.now().isoformat(timespec='milliseconds')} "
                f"worker={worker_id} pid={os.getpid()} ---\n"
            )
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=fh)
    except Exception:
        # Never let diagnostics break the crash path.
        pass


def _pool_worker(
    config: SootheConfig,
    worker_id: str,
    request_queue: multiprocessing.Queue,
    response_queue: multiprocessing.Queue,
    cancel_event: multiprocessing.Event,
    idle_timeout_seconds: int,
    max_requests: int,
    default_timeout_seconds: int,
    heartbeat_interval_seconds: int,
) -> None:
    """Multiprocessing entry: delegate to body and record fatal errors on disk."""
    try:
        _pool_worker_body(
            config,
            worker_id,
            request_queue,
            response_queue,
            cancel_event,
            idle_timeout_seconds,
            max_requests,
            default_timeout_seconds,
            heartbeat_interval_seconds,
        )
    except BaseException as exc:
        if type(exc) is GeneratorExit:
            raise
        if isinstance(exc, SystemExit) and exc.code in (0, None, False):
            raise
        _log_pool_worker_fatal(worker_id, exc)
        raise


def _pool_worker_body(
    config: SootheConfig,
    worker_id: str,
    request_queue: multiprocessing.Queue,
    response_queue: multiprocessing.Queue,
    cancel_event: multiprocessing.Event,
    idle_timeout_seconds: int,
    max_requests: int,
    default_timeout_seconds: int,
    heartbeat_interval_seconds: int,
) -> None:
    """Worker subprocess body: wait for requests and execute loop runs.

    The multiprocessing entrypoint is ``_pool_worker`` (wraps this function).

    Behavior:
        - Wait for requests on request_queue (with idle timeout)
        - Create fresh SootheRunner per request (no user data leakage)
        - Execute request, stream results to response_queue
        - Check cancel_event between chunks for cooperative cancellation
        - Send heartbeat messages on a background thread (independent of chunk cadence
          and event-loop blocking during sync work such as model downloads)
        - Exit on shutdown sentinel, idle timeout, or max requests

    Args:
        config: Spawn-safe SootheConfig.
        worker_id: Unique worker identifier for logging.
        request_queue: Queue for receiving requests from main process.
        response_queue: Queue for sending responses to main process.
        cancel_event: multiprocessing.Event for cooperative cancellation signaling.
        idle_timeout_seconds: Exit after this many seconds idle.
        max_requests: Exit after this many requests completed.
        default_timeout_seconds: Default per-request timeout if not specified.
        heartbeat_interval_seconds: Interval for sending heartbeat messages.
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

        # Clear cancel event at start of new request
        cancel_event.clear()

        # Determine timeout: use request-specific or default
        timeout_seconds = (
            req.timeout_seconds
            if req.timeout_seconds and req.timeout_seconds > 0
            else default_timeout_seconds
        )
        timeout_enabled = timeout_seconds > 0

        async def _execute() -> None:
            # SootheRunner inside try so constructor failures surface as protocol errors,
            # not a silent worker process exit (BaseException would bypass except Exception).
            runner: SootheRunner | None = None

            try:
                runner = SootheRunner(config)

                # Use asyncio.timeout for overall request timeout if enabled
                timeout_ctx = _asyncio.timeout(timeout_seconds) if timeout_enabled else None

                heartbeat_stop = threading.Event()
                heartbeat_start = time.monotonic()
                heartbeat_thread: threading.Thread | None = None

                async def _stream() -> None:
                    async for chunk in runner.astream(
                        req.user_input,
                        thread_id=req.thread_id,
                        workspace=req.resolve_workspace_path(),
                        max_iterations=req.max_iterations,
                        preferred_subagent=req.preferred_subagent,
                        client_loop_id=req.loop_id,
                        intent_hint=parse_intent_hint(req.intent_hint),
                        autopilot_job=req.autopilot_job,  # RFC-222 revised
                        clarification_mode=req.clarification_mode,
                        clarification_answer=req.clarification_answer,
                        clarification_answers=req.clarification_answers,
                    ):
                        # COOPERATIVE CANCELLATION: Check cancel_event between chunks
                        if cancel_event.is_set():
                            logger.info(
                                "Worker %s: cancellation requested for loop=%s request_id=%s",
                                worker_id,
                                req.loop_id,
                                request_id,
                            )
                            response_queue.put(("cancelled", request_id, None))
                            return

                        # Tag response with request_id for routing
                        response_queue.put(("chunk", request_id, chunk))

                    response_queue.put(("done", request_id, None))

                async def _stream_with_heartbeat() -> None:
                    nonlocal heartbeat_thread
                    # Prime stuck-detection so busy workers are not flagged before first tick.
                    response_queue.put(
                        ("heartbeat", request_id, {"elapsed_seconds": 0.0}),
                    )
                    heartbeat_thread = _start_thread_heartbeat(
                        response_queue=response_queue,
                        request_id=request_id,
                        stop_event=heartbeat_stop,
                        heartbeat_interval_seconds=float(heartbeat_interval_seconds),
                        start_time=heartbeat_start,
                    )
                    stream_task = _asyncio.create_task(_stream())

                    async def _poll_cancel_event() -> None:
                        """Cancel the stream task when the main process sets cancel_event.

                        Without this, cooperative cancel is only observed between
                        ``runner.astream`` chunks; long tool/subagent awaits never
                        re-enter the outer loop to check ``cancel_event``.
                        """
                        try:
                            while True:
                                await _asyncio.sleep(0.25)
                                if cancel_event.is_set():
                                    stream_task.cancel()
                                    return
                        except _asyncio.CancelledError:
                            raise

                    poll_task = _asyncio.create_task(_poll_cancel_event())
                    try:
                        await stream_task
                    finally:
                        heartbeat_stop.set()
                        poll_task.cancel()
                        try:
                            await poll_task
                        except _asyncio.CancelledError:
                            pass
                        if heartbeat_thread is not None:
                            heartbeat_thread.join(timeout=2.0)

                if timeout_ctx:
                    async with timeout_ctx:
                        await _stream_with_heartbeat()
                else:
                    await _stream_with_heartbeat()

            except _asyncio.CancelledError:
                # Since Python 3.8 CancelledError does not inherit Exception; uncaught it
                # would abort this worker process and strand the parent on a dead worker.
                logger.warning(
                    "Worker %s: asyncio.CancelledError during request loop=%s request_id=%s",
                    worker_id,
                    req.loop_id,
                    request_id,
                )
                response_queue.put(("cancelled", request_id, None))
            except TimeoutError:
                logger.warning(
                    "Worker %s: request timeout (%ds) for loop=%s request_id=%s",
                    worker_id,
                    timeout_seconds,
                    req.loop_id,
                    request_id,
                )
                response_queue.put(
                    (
                        "timeout",
                        request_id,
                        RuntimeError(f"Request exceeded {timeout_seconds}s timeout"),
                    )
                )
            except Exception as exc:
                response_queue.put(("error", request_id, exc))
            finally:
                # Per-request runners own PostgreSQL checkpointer pools; without cleanup,
                # connections accumulate across requests and PoolTimeout can occur.
                if runner is None:
                    return
                try:
                    await runner.cleanup()
                except _asyncio.CancelledError:
                    logger.debug(
                        "Worker %s: runner cleanup cancelled (loop=%s request_id=%s)",
                        worker_id,
                        req.loop_id,
                        request_id,
                    )
                except Exception:
                    logger.debug(
                        "Worker %s: runner cleanup failed (loop=%s request_id=%s)",
                        worker_id,
                        req.loop_id,
                        request_id,
                        exc_info=True,
                    )

        try:
            loop.run_until_complete(_execute())
        except _asyncio.CancelledError:
            logger.warning(
                "Worker %s: run_until_complete raised CancelledError loop=%s request_id=%s",
                worker_id,
                req.loop_id,
                request_id,
            )
            try:
                response_queue.put(("cancelled", request_id, None))
            except Exception:
                logger.exception(
                    "Worker %s: failed to enqueue cancelled after CancelledError request_id=%s",
                    worker_id,
                    request_id,
                )
        except Exception as exc:
            # Last-resort: anything that escaped _execute (e.g. sync code after await chain).
            logger.exception(
                "Worker %s: uncaught exception in run_until_complete loop=%s request_id=%s",
                worker_id,
                req.loop_id,
                request_id,
            )
            try:
                response_queue.put(("error", request_id, exc))
            except Exception:
                logger.exception(
                    "Worker %s: failed to enqueue error after fatal failure request_id=%s",
                    worker_id,
                    request_id,
                )

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

    Dynamic Scaling (min/max pool size):
        - Starts with min_pool_size workers at daemon startup
        - Grows up to max_pool_size when all min workers are busy
        - Workers beyond min_pool_size idle out after idle_timeout_seconds
        - Shrinks back to min_pool_size when load decreases

    Architecture:
        Daemon → LoopRunnerFactory → WorkerPool (singleton)
                                         ↓
        WorkerProcess[0..N]
            ← request_queue (dispatch requests)
            → response_queue (stream responses)

    Lifecycle:
        - Startup: pre-warm min_pool_size workers
        - Runtime: workers pull requests, execute, return to pool
        - Scaling: spawn extra workers when needed, idle out when not
        - Shutdown: signal all workers to exit, wait, then force-kill
    """

    _shared_pool: WorkerPool | None = None
    _pool_lock: asyncio.Lock | None = None

    def __init__(
        self,
        config: SootheConfig,
        min_pool_size: int = 2,
        max_pool_size: int = 4,
        idle_timeout_seconds: int = 300,
        max_requests_per_worker: int = 100,
        request_timeout_seconds: int = 0,
        heartbeat_interval_seconds: int = 30,
        stuck_worker_timeout_seconds: int = 180,
        dispatch_wait_stats_enabled: bool = False,
        dispatch_wait_stats_interval_seconds: int = 60,
        dispatch_wait_stats_idle_pause_seconds: int = 120,
    ) -> None:
        self._config = config
        self._min_pool_size = min_pool_size
        self._max_pool_size = max(min_pool_size, max_pool_size)  # Ensure max >= min
        self._idle_timeout_seconds = idle_timeout_seconds
        self._max_requests_per_worker = max_requests_per_worker
        self._request_timeout_seconds = request_timeout_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._stuck_worker_timeout_seconds = stuck_worker_timeout_seconds
        self._dispatch_wait_stats_enabled = dispatch_wait_stats_enabled
        self._dispatch_wait_stats_interval_seconds = dispatch_wait_stats_interval_seconds
        self._dispatch_wait_stats_idle_pause_seconds = dispatch_wait_stats_idle_pause_seconds

        self._ctx = multiprocessing.get_context("spawn")
        self._workers: dict[str, WorkerProcess] = {}
        self._workers_by_loop_id: dict[str, str] = {}  # loop_id -> worker_id
        self._dispatch_semaphore: asyncio.Semaphore | None = None
        self._worker_available: asyncio.Condition | None = None
        self._waiting_for_worker_slot: int = 0
        self._dispatch_stats: PoolDispatchWaitStatsCollector | None = None
        self._dispatch_stats_task: asyncio.Task[None] | None = None
        self._running = False
        self._metrics_requests_total = 0
        self._metrics_latencies: list[float] = []
        # Track pending responses by request_id
        self._pending_responses: dict[str, asyncio.Queue] = {}
        self._health_task: asyncio.Task | None = None
        self._bridge_tasks: dict[str, asyncio.Task[None]] = {}
        # Client disconnect: finish routing worker stream until done/error
        self._abandon_drain_tasks: set[asyncio.Task[None]] = set()
        # Next worker slot index for scaling up
        self._next_worker_index: int = 0
        #: Consecutive "fast" deaths per slot (respawn storm mitigation).
        self._worker_rapid_death_streak: dict[str, int] = {}
        self._worker_last_death_monotonic: dict[str, float] = {}

    @classmethod
    async def get_shared_instance(
        cls, config: SootheConfig, daemon_config: SootheDaemonConfig
    ) -> WorkerPool:
        """Get or create the singleton pool instance."""
        if cls._shared_pool is not None:
            return cls._shared_pool

        if cls._pool_lock is None:
            cls._pool_lock = asyncio.Lock()

        async with cls._pool_lock:
            if cls._shared_pool is not None:
                return cls._shared_pool

            pool_config = daemon_config.worker_pool
            pool = WorkerPool(
                config=config,
                min_pool_size=pool_config.min_pool_size,
                max_pool_size=pool_config.get_effective_pool_size(),
                idle_timeout_seconds=pool_config.idle_timeout_seconds,
                max_requests_per_worker=pool_config.max_requests_per_worker,
                request_timeout_seconds=pool_config.request_timeout_seconds,
                heartbeat_interval_seconds=pool_config.heartbeat_interval_seconds,
                stuck_worker_timeout_seconds=pool_config.stuck_worker_timeout_seconds,
                dispatch_wait_stats_enabled=pool_config.dispatch_wait_stats_enabled,
                dispatch_wait_stats_interval_seconds=pool_config.dispatch_wait_stats_interval_seconds,
                dispatch_wait_stats_idle_pause_seconds=pool_config.dispatch_wait_stats_idle_pause_seconds,
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
        """Pre-warm min_pool_size worker processes."""
        self._dispatch_semaphore = asyncio.Semaphore(self._max_pool_size)
        self._worker_available = asyncio.Condition()
        if self._dispatch_wait_stats_enabled:
            self._dispatch_stats = PoolDispatchWaitStatsCollector()
        spawn_config = _spawn_safe_config(self._config)

        # Pre-warm only min_pool_size workers at startup
        for i in range(self._min_pool_size):
            worker_id = f"worker-{i}"
            await self._spawn_worker(worker_id, spawn_config)
            self._next_worker_index = i + 1

        self._running = True
        self._health_task = asyncio.create_task(self._worker_health_watchdog())
        if self._dispatch_stats is not None:
            self._dispatch_stats_task = asyncio.create_task(self._periodic_dispatch_stats())

        logger.info(
            "WorkerPool: pre-warmed %d workers (min=%d, max=%d, idle_timeout=%ds, max_requests=%d)",
            self._min_pool_size,
            self._min_pool_size,
            self._max_pool_size,
            self._idle_timeout_seconds,
            self._max_requests_per_worker,
        )

    async def _spawn_worker(self, worker_id: str, config: SootheConfig) -> WorkerProcess:
        """Spawn a single worker process with request/response queues and cancel event."""
        request_queue: Any = self._ctx.Queue()
        response_queue: Any = self._ctx.Queue()
        cancel_event: Any = self._ctx.Event()

        process = self._ctx.Process(
            target=_pool_worker,
            args=(
                config,
                worker_id,
                request_queue,
                response_queue,
                cancel_event,
                self._idle_timeout_seconds,
                self._max_requests_per_worker,
                self._request_timeout_seconds,
                self._heartbeat_interval_seconds,
            ),
            daemon=True,
            name=worker_id,
        )
        process.start()

        worker = WorkerProcess(
            process=process,
            request_queue=request_queue,
            response_queue=response_queue,
            cancel_event=cancel_event,
            worker_id=worker_id,
            started_at=datetime.now(),
        )
        self._workers[worker_id] = worker
        self._start_worker_bridge(worker_id)

        logger.debug("WorkerPool: spawned worker %s (pid=%d)", worker_id, process.pid)
        return worker

    def _start_worker_bridge(self, worker_id: str) -> None:
        """Start per-worker response bridge (blocking mp get → asyncio queue, IG-429)."""
        old = self._bridge_tasks.pop(worker_id, None)
        if old is not None:
            old.cancel()
        self._bridge_tasks[worker_id] = asyncio.create_task(
            self._bridge_worker_responses(worker_id),
            name=f"pool-bridge-{worker_id}",
        )

    async def _bridge_worker_responses(self, worker_id: str) -> None:
        """Route worker mp.Queue messages without 50ms poll throttle."""
        loop = asyncio.get_event_loop()

        while self._running:
            worker = self._workers.get(worker_id)
            if worker is None:
                break

            try:
                msg = await loop.run_in_executor(
                    None,
                    worker.response_queue.get,
                    True,
                    0.5,
                )
            except queue.Empty:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                if not self._running:
                    break
                logger.debug(
                    "WorkerPool: bridge read failed worker=%s",
                    worker_id,
                    exc_info=True,
                )
                continue

            if not isinstance(msg, tuple) or len(msg) != 3:
                logger.debug(
                    "WorkerPool: bridge ignoring malformed message worker=%s: %r",
                    worker_id,
                    msg,
                )
                continue

            msg_type, request_id, payload = msg
            await self._route_worker_message(worker, msg_type, request_id, payload)

    async def _route_worker_message(
        self,
        worker: WorkerProcess,
        msg_type: str,
        request_id: str,
        payload: Any,
    ) -> None:
        """Deliver one worker message to the pending asyncio response queue."""
        worker_id = worker.worker_id

        if msg_type == "heartbeat":
            worker.last_heartbeat_at = datetime.now()
            logger.debug(
                "WorkerPool: heartbeat from worker=%s request_id=%s elapsed=%.1fs",
                worker_id,
                request_id,
                payload.get("elapsed_seconds", 0) if isinstance(payload, dict) else 0,
            )
            return

        if msg_type == "timeout":
            response_queue = self._pending_responses.get(request_id)
            if response_queue is not None:
                await response_queue.put(("error", payload))
            await self._mark_worker_idle_and_notify(worker)
            self._workers_by_loop_id.pop(worker.current_loop_id or "", None)
            self._pending_responses.pop(request_id, None)
            logger.warning(
                "WorkerPool: worker %s request %s timed out",
                worker_id,
                request_id,
            )
            return

        if msg_type == "cancelled":
            response_queue = self._pending_responses.get(request_id)
            if response_queue is not None:
                await response_queue.put(("error", asyncio.CancelledError()))
            await self._mark_worker_idle_and_notify(worker)
            self._workers_by_loop_id.pop(worker.current_loop_id or "", None)
            self._pending_responses.pop(request_id, None)
            logger.info(
                "WorkerPool: worker %s request %s cancelled cooperatively",
                worker_id,
                request_id,
            )
            return

        response_queue = self._pending_responses.get(request_id)
        if response_queue is not None:
            await response_queue.put((msg_type, payload))
            if worker.status == WorkerStatus.BUSY:
                worker.last_heartbeat_at = datetime.now()
        else:
            logger.debug(
                "WorkerPool: no pending route for request_id=%s (%s); discarding",
                request_id,
                msg_type,
            )

    def _schedule_abandon_drain(
        self,
        worker: WorkerProcess,
        loop_id: str,
        request_id: str,
        response_queue: asyncio.Queue,
    ) -> None:
        """After client disconnect, keep routing until worker sends done/error."""

        async def _run() -> None:
            try:
                await self._drain_abandoned_request(worker, loop_id, request_id, response_queue)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "WorkerPool: abandon drain failed for worker=%s request_id=%s",
                    worker.worker_id,
                    request_id,
                )
                await self._mark_worker_idle_and_notify(worker)
                self._workers_by_loop_id.pop(loop_id, None)
                self._pending_responses.pop(request_id, None)

        task = asyncio.create_task(_run(), name=f"pool-abandon-{request_id}")
        self._abandon_drain_tasks.add(task)
        task.add_done_callback(self._abandon_drain_tasks.discard)

    async def _drain_abandoned_request(
        self,
        worker: WorkerProcess,
        loop_id: str,
        request_id: str,
        response_queue: asyncio.Queue,
    ) -> None:
        """Consume stream after the client left; release worker when the run completes."""
        chunks_discarded = 0
        try:
            while True:
                msg_type, payload = await response_queue.get()
                if msg_type == "chunk":
                    chunks_discarded += 1
                    continue
                if msg_type == "heartbeat":
                    # Update heartbeat timestamp but don't count as chunk
                    worker.last_heartbeat_at = datetime.now()
                    continue
                if msg_type == "done":
                    worker.requests_completed += 1
                    logger.info(
                        "WorkerPool: client disconnected; finished worker %s request %s "
                        "(%d chunk(s) not delivered)",
                        worker.worker_id,
                        request_id,
                        chunks_discarded,
                    )
                    return
                if msg_type == "error":
                    worker.requests_completed += 1
                    logger.info(
                        "WorkerPool: client disconnected; worker %s request %s ended with "
                        "error after %d undelivered chunk(s): %s",
                        worker.worker_id,
                        request_id,
                        chunks_discarded,
                        payload,
                    )
                    return
                if msg_type == "timeout":
                    worker.requests_completed += 1
                    logger.info(
                        "WorkerPool: client disconnected; worker %s request %s timed out "
                        "after %d undelivered chunk(s)",
                        worker.worker_id,
                        request_id,
                        chunks_discarded,
                    )
                    return
                if msg_type == "cancelled":
                    worker.requests_completed += 1
                    logger.info(
                        "WorkerPool: client disconnected; worker %s request %s cancelled "
                        "after %d undelivered chunk(s)",
                        worker.worker_id,
                        request_id,
                        chunks_discarded,
                    )
                    return
                logger.debug(
                    "WorkerPool: unexpected msg_type=%s in abandon drain for request_id=%s",
                    msg_type,
                    request_id,
                )
                break
        finally:
            await self._mark_worker_idle_and_notify(worker)
            self._workers_by_loop_id.pop(loop_id, None)
            self._pending_responses.pop(request_id, None)

    async def _route_failure_for_dead_busy_worker(self, worker: WorkerProcess) -> None:
        """If a worker process died while handling a request, unblock the waiter with an error.

        Without this, ``submit()`` blocks forever on ``response_queue.get()`` because the
        poll loop previously skipped dead workers and never forwarded ``done``/``error``.
        """
        req_id = worker.current_request_id
        if req_id is None or worker.dead_failure_routed:
            return

        aio_q = self._pending_responses.get(req_id)
        if aio_q is None:
            logger.warning(
                "WorkerPool: worker %s died while busy but no pending route (request_id=%s)",
                worker.worker_id,
                req_id,
            )
            worker.dead_failure_routed = True
            return

        worker.dead_failure_routed = True
        exitcode = worker.process.exitcode
        exit_hint = (
            f" (worker exit code: {exitcode})"
            if exitcode is not None
            else " (worker exit code: unknown)"
        )
        err = RuntimeError(
            "Worker subprocess exited unexpectedly during query execution; "
            "check daemon logs for worker or model errors." + exit_hint
        )
        try:
            await aio_q.put(("error", err))
        except Exception:
            worker.dead_failure_routed = False
            logger.exception(
                "WorkerPool: failed to deliver dead-worker error for request_id=%s",
                req_id,
            )

    async def _handle_dead_worker(self, worker: WorkerProcess) -> None:
        """Recover from a dead OS process: fail in-flight work and respawn the slot."""
        logger.warning(
            "WorkerPool: worker %s OS process ended (exitcode=%s, busy=%s, request_id=%s)",
            worker.worker_id,
            worker.process.exitcode,
            worker.status == WorkerStatus.BUSY,
            worker.current_request_id,
        )
        if worker.current_request_id is not None:
            await self._route_failure_for_dead_busy_worker(worker)

        wid = worker.worker_id
        now = time.monotonic()
        last = self._worker_last_death_monotonic.get(wid, 0.0)
        if now - last <= 2.0:
            self._worker_rapid_death_streak[wid] = self._worker_rapid_death_streak.get(wid, 0) + 1
        else:
            self._worker_rapid_death_streak[wid] = 1
        self._worker_last_death_monotonic[wid] = now

        streak = self._worker_rapid_death_streak[wid]
        if streak >= 5:
            backoff = min(30.0, 0.2 * (2.0 ** min(streak - 5, 8)))
            crash_log = Path(SOOTHE_HOME) / "logs" / "pool_worker_bootstrap.log"
            logger.error(
                "WorkerPool: worker %s died %d times in quick succession; "
                "waiting %.1fs before respawn (if the child crashes on startup, see %s)",
                wid,
                streak,
                backoff,
                crash_log,
            )
            await asyncio.sleep(backoff)

        try:
            await self._respawn_worker(worker)
        except Exception:
            logger.exception("WorkerPool: failed to respawn dead worker %s", worker.worker_id)

    async def _worker_health_watchdog(self) -> None:
        """Stuck/dead worker detection and idle stale-queue drain (no chunk relay; IG-429)."""
        loop = asyncio.get_event_loop()

        while self._running:
            for worker_id, worker in list(self._workers.items()):
                if worker.is_alive():
                    age_sec = (datetime.now() - worker.started_at).total_seconds()
                    if age_sec >= 5.0:
                        self._worker_rapid_death_streak.pop(worker_id, None)

                if worker.status == WorkerStatus.BUSY:
                    now = datetime.now()
                    if worker.last_heartbeat_at is not None:
                        heartbeat_age = (now - worker.last_heartbeat_at).total_seconds()
                        if heartbeat_age > self._stuck_worker_timeout_seconds:
                            logger.warning(
                                "WorkerPool: worker %s stuck (no heartbeat for %.0fs, request_id=%s)",
                                worker_id,
                                heartbeat_age,
                                worker.current_request_id,
                            )
                            await self._handle_stuck_worker(worker)
                            continue
                    else:
                        elapsed = (now - worker.last_activity).total_seconds()
                        if elapsed > self._stuck_worker_timeout_seconds * 2:
                            logger.warning(
                                "WorkerPool: worker %s never sent heartbeat (%.0fs since dispatch, request_id=%s)",
                                worker_id,
                                elapsed,
                                worker.current_request_id,
                            )
                            await self._handle_stuck_worker(worker)
                            continue

                if not worker.is_alive():
                    await self._handle_dead_worker(worker)
                    continue

                if worker.current_request_id is not None:
                    continue

                drained = 0
                last_kind: str | None = None
                while True:
                    try:
                        msg = await loop.run_in_executor(
                            None,
                            worker.response_queue.get_nowait,
                        )
                    except queue.Empty:
                        break
                    drained += 1
                    last_kind = msg[0]
                if drained:
                    logger.debug(
                        "WorkerPool: drained %d stale response(s) from idle worker %s (last=%s)",
                        drained,
                        worker_id,
                        last_kind,
                    )

            await asyncio.sleep(1.0)

    async def _handle_stuck_worker(self, worker: WorkerProcess) -> None:
        """Handle a worker that hasn't sent heartbeat for too long."""
        logger.warning(
            "WorkerPool: terminating stuck worker %s (request_id=%s)",
            worker.worker_id,
            worker.current_request_id,
        )

        # Route failure to pending request
        if worker.current_request_id:
            await self._route_failure_for_dead_busy_worker(worker)

        # Terminate stuck worker process
        if worker.process.is_alive():
            worker.process.terminate()
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: worker.process.join(timeout=5)
                )
            except Exception:
                pass

        # Respawn worker slot
        try:
            await self._respawn_worker(worker)
        except Exception:
            logger.exception("WorkerPool: failed to respawn stuck worker %s", worker.worker_id)

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
        await self._notify_worker_slot_available()

    async def _periodic_dispatch_stats(self) -> None:
        stats = self._dispatch_stats
        if stats is None:
            return
        interval = float(self._dispatch_wait_stats_interval_seconds)
        idle_pause = float(self._dispatch_wait_stats_idle_pause_seconds)
        while self._running:
            await asyncio.sleep(interval)
            try:
                await stats.emit_log_if_active(
                    idle_pause_seconds=idle_pause,
                    log_fn=logger.info,
                )
            except Exception:
                logger.debug("pool_dispatch_stats periodic tick failed", exc_info=True)

    async def _notify_worker_slot_available(self) -> None:
        cond = self._worker_available
        if cond is None:
            return
        async with cond:
            cond.notify_all()

    async def _mark_worker_idle_and_notify(self, worker: WorkerProcess) -> None:
        worker.mark_idle()
        await self._notify_worker_slot_available()

    async def _try_acquire_idle_worker(self) -> WorkerProcess | None:
        """Return an idle live worker, scale up, or respawn a dead slot; else None."""
        for w in self._workers.values():
            if w.status == WorkerStatus.IDLE and w.is_alive():
                return w

        active_count = sum(1 for w in self._workers.values() if w.is_alive())
        if active_count < self._max_pool_size:
            worker_id = f"worker-{self._next_worker_index}"
            self._next_worker_index += 1
            spawn_config = _spawn_safe_config(self._config)
            logger.info(
                "WorkerPool: scaling up, spawning extra worker %s (active=%d, max=%d)",
                worker_id,
                active_count + 1,
                self._max_pool_size,
            )
            return await self._spawn_worker(worker_id, spawn_config)

        for w in self._workers.values():
            if w.status == WorkerStatus.DEAD or not w.is_alive():
                await self._respawn_worker(w)
                return self._workers[w.worker_id]

        return None

    async def submit(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Submit request to pool, await available worker, stream results.

        Dynamic scaling: If all min_pool_size workers are busy, spawns extra
        workers up to max_pool_size. Extra workers idle out after idle_timeout.
        """
        # Generate unique request_id for this request
        request_id = uuid.uuid4().hex[:16]

        # Set timeout on request if not specified
        if request.timeout_seconds is None or request.timeout_seconds <= 0:
            request.timeout_seconds = (
                self._request_timeout_seconds if self._request_timeout_seconds > 0 else None
            )

        dispatch_wait_start = time.monotonic()
        # Wait for available worker slot (bounded by max_pool_size semaphore).
        # When all workers are busy at max_pool_size, wait on a condition until a worker
        # becomes idle (or the pool scales / respawns a dead process).
        async with self._dispatch_semaphore:
            cond = self._worker_available
            if cond is None:
                raise RuntimeError("Worker pool is not started")

            worker: WorkerProcess
            response_queue: asyncio.Queue
            handoff_retries = 0
            while True:
                while True:
                    worker = await self._try_acquire_idle_worker()
                    if worker is not None:
                        break
                    if not self._running:
                        raise RuntimeError("Worker pool is shutting down")
                    async with cond:
                        self._waiting_for_worker_slot += 1
                        try:
                            if self._dispatch_stats is not None:
                                await self._dispatch_stats.record_waiter_snapshot(
                                    self._waiting_for_worker_slot
                                )
                            await cond.wait()
                        finally:
                            self._waiting_for_worker_slot -= 1

                # Register routing and mark busy before releasing the semaphore so the poll
                # loop cannot treat this worker as idle and drain a stale response_queue.
                response_queue = asyncio.Queue()
                self._pending_responses[request_id] = response_queue
                self._workers_by_loop_id[request.loop_id] = worker.worker_id
                worker.mark_busy(request.loop_id, request_id)
                worker.request_queue.put(("request", request_id, request))
                if worker.is_alive():
                    break

                # Worker exited after we observed it idle (common race: subprocess idle
                # timeout vs dispatch). Recover without surfacing a client RuntimeError.
                self._pending_responses.pop(request_id, None)
                self._workers_by_loop_id.pop(request.loop_id, None)
                worker.mark_idle()
                handoff_retries += 1
                if handoff_retries > 64:
                    raise RuntimeError(
                        "Worker pool: unable to hand off request after repeated worker exits; "
                        "see daemon logs."
                    )
                logger.info(
                    "WorkerPool: worker %s exited during dispatch handoff "
                    "(often idle timeout vs acquire); recovering",
                    worker.worker_id,
                )
                await self._handle_dead_worker(worker)

            wait_ms = (time.monotonic() - dispatch_wait_start) * 1000.0
            if self._dispatch_stats is not None:
                await self._dispatch_stats.record_dispatch_handoff(wait_ms)

        start_time = datetime.now()
        completed = False

        try:
            while True:
                msg_type, payload = await response_queue.get()

                if msg_type == "done":
                    completed = True
                    await self._mark_worker_idle_and_notify(worker)
                    self._workers_by_loop_id.pop(request.loop_id, None)
                    self._pending_responses.pop(request_id, None)
                    self._metrics_requests_total += 1
                    latency_ms = (datetime.now() - start_time).total_seconds() * 1000
                    self._metrics_latencies.append(latency_ms)
                    worker.requests_completed += 1
                    return
                if msg_type == "error":
                    completed = True
                    await self._mark_worker_idle_and_notify(worker)
                    self._workers_by_loop_id.pop(request.loop_id, None)
                    self._pending_responses.pop(request_id, None)
                    raise payload

                # msg_type == "chunk"
                yield payload
        except asyncio.CancelledError:
            logger.info("Pool request %s cancelled by client disconnect", request_id)
            raise
        finally:
            if not completed:
                # Client left (cancel, disconnect, or early close): worker may still be
                # streaming — keep routing until done/error so the worker returns idle
                # without flooding orphan logs.
                self._schedule_abandon_drain(worker, request.loop_id, request_id, response_queue)

    async def cancel_request(self, loop_id: str) -> None:
        """Signal cooperative cancellation to worker handling this loop_id.

        Sets the worker's cancel_event to signal the worker process to stop
        between stream chunks. The worker will send a "cancelled" message
        back when it detects the signal.
        """
        worker_id = self._workers_by_loop_id.get(loop_id)
        if worker_id is None:
            logger.debug("WorkerPool: no active request for loop_id=%s", loop_id)
            return

        worker = self._workers.get(worker_id)
        if worker is None:
            logger.debug("WorkerPool: worker %s not found for loop_id=%s", worker_id, loop_id)
            return

        # Set the cancellation Event (inherited by worker process at spawn)
        worker.cancel_event.set()

        logger.info(
            "WorkerPool: cancellation signal sent for loop_id=%s to worker=%s",
            loop_id,
            worker_id,
        )

    async def force_kill_worker(self, worker_id: str, timeout: float = 10.0) -> None:
        """Force terminate a worker process after cooperative cancel fails.

        Guarantees the worker is terminated by SIGTERM then SIGKILL if needed.

        Args:
            worker_id: Worker to terminate.
            timeout: Seconds to wait for process death after terminate.
        """
        worker = self._workers.get(worker_id)
        if worker is None:
            logger.debug("force_kill_worker: worker %s not found", worker_id)
            return

        if not worker.process.is_alive():
            # Already dead - cleanup bookkeeping
            logger.debug("force_kill_worker: worker %s already dead, cleaning up", worker_id)
            self._workers.pop(worker_id, None)
            loop_id = worker.current_loop_id or ""
            self._workers_by_loop_id.pop(loop_id, None)
            self._pending_responses.pop(worker.current_request_id or "", None)
            return

        logger.warning(
            "Force killing worker %s (loop_id=%s)",
            worker_id,
            worker.current_loop_id,
        )
        worker.status = WorkerStatus.SHUTTING_DOWN

        loop = asyncio.get_event_loop()

        # SIGTERM first (graceful termination)
        try:
            worker.process.terminate()
            await asyncio.wait_for(
                loop.run_in_executor(None, lambda: worker.process.join(timeout=timeout / 2)),
                timeout=timeout / 2 + 1,
            )
        except TimeoutError:
            pass

        # SIGKILL if still alive
        if worker.process.is_alive():
            logger.warning("Worker %s did not respond to terminate, killing", worker_id)
            worker.process.kill()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: worker.process.join(timeout=2)),
                    timeout=3,
                )
            except TimeoutError:
                logger.error("Worker %s zombie after kill", worker_id)

        # Cleanup bookkeeping
        self._workers.pop(worker_id, None)
        loop_id = worker.current_loop_id or ""
        self._workers_by_loop_id.pop(loop_id, None)
        self._pending_responses.pop(worker.current_request_id or "", None)

        logger.info("Worker %s force terminated", worker_id)

    def get_worker_id_for_loop(self, loop_id: str) -> str | None:
        """Return worker_id handling the given loop_id, if any."""
        return self._workers_by_loop_id.get(loop_id)

    def is_worker_idle(self, worker_id: str) -> bool:
        """Check if worker has returned to idle state."""
        worker = self._workers.get(worker_id)
        if worker is None:
            return True  # Gone means cancelled
        return worker.status == WorkerStatus.IDLE or not worker.process.is_alive()

    async def shutdown(self) -> None:
        """Graceful shutdown: signal workers, wait, then force-kill."""
        self._running = False

        await self._notify_worker_slot_available()

        if self._dispatch_stats_task is not None:
            self._dispatch_stats_task.cancel()
            try:
                await self._dispatch_stats_task
            except asyncio.CancelledError:
                pass
            self._dispatch_stats_task = None

        if self._health_task is not None:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None

        for task in list(self._bridge_tasks.values()):
            task.cancel()
        for task in list(self._bridge_tasks.values()):
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._bridge_tasks.clear()

        for t in list(self._abandon_drain_tasks):
            t.cancel()
        for t in list(self._abandon_drain_tasks):
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._abandon_drain_tasks.clear()

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
            total_workers=self._max_pool_size,
            idle_workers=idle,
            busy_workers=busy,
            dead_workers=dead,
            total_requests_completed=self._metrics_requests_total,
            requests_in_progress=busy,
            avg_request_latency_ms=avg_latency,
            worker_uptimes=uptimes,
            dispatch_waiters_waiting=self._waiting_for_worker_slot,
        )


class PoolLoopRunner:
    """Runs agent loops using the persistent worker pool.

    Implements LoopRunnerProtocol for integration with QueryEngine.
    One instance per loop_id, created by LoopRunnerFactory.
    """

    def __init__(
        self,
        loop_id: str,
        config: SootheConfig,
        daemon_config: SootheDaemonConfig,
    ) -> None:
        self._loop_id = loop_id
        self._config = config
        self._daemon_config = daemon_config
        self._pool: WorkerPool | None = None

    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Delegate to shared pool, stream results."""
        pool = await WorkerPool.get_shared_instance(self._config, self._daemon_config)
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
