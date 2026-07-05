"""Thread pool for loop execution.

Uses threads instead of subprocesses for lower overhead (~ms vs ~8s spawn).
Each thread maintains a dedicated asyncio event loop for LangGraph streaming.
One reused SootheRunner per worker (``prepare_for_request`` between turns) keeps
startup cost low while isolating per-request state.

ARCHITECTURE: Each worker thread has queues for cross-thread communication:
    - request_queue: main process → worker thread (dispatch requests)
    - response_queue: worker thread → main process (stream responses)
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from soothe.config.settings import SootheConfig
from soothe.protocols.runner import LoopRunRequest

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.runner.response_bridge import ResponsePusher

if TYPE_CHECKING:
    from soothe.middleware.identity import IdentityRuntime
    from soothe.runner._runner_shared import StreamChunk

logger = logging.getLogger(__name__)

_RESPONSE_QUEUE_MAXSIZE = 200  # IG-535: dense streaming under many concurrent loops

# Last error per worker thread (survives unexpected thread exit for watchdog logs).
_worker_last_errors: dict[str, str] = {}
_worker_last_errors_lock = threading.Lock()


def _record_worker_last_error(worker_id: str, exc: BaseException) -> None:
    with _worker_last_errors_lock:
        _worker_last_errors[worker_id] = f"{type(exc).__name__}: {exc}"


def _pop_worker_last_error(worker_id: str) -> str | None:
    with _worker_last_errors_lock:
        return _worker_last_errors.pop(worker_id, None)


class WorkerThreadStatus(StrEnum):
    """Worker thread status."""

    IDLE = "idle"
    BUSY = "busy"
    CLEANING_UP = "cleaning_up"
    SHUTTING_DOWN = "shutting_down"
    DEAD = "dead"


_TERMINAL_RESPONSE_TYPES = frozenset({"done", "error", "timeout", "cancelled"})


@dataclass
class WorkerThreadState:
    """State for a single worker thread in the pool."""

    thread: threading.Thread
    request_queue: queue.Queue  # main → worker (threading.Queue)
    response_queue: queue.Queue  # worker → main (threading.Queue)
    cancel_event: threading.Event  # cooperative cancellation signal
    stop_event: threading.Event  # shutdown signal
    worker_id: str
    #: Baseline slots (index < min_pool_size) stay warm; scaled slots idle out.
    is_baseline: bool = True
    status: WorkerThreadStatus = WorkerThreadStatus.IDLE
    current_loop_id: str | None = None
    current_request_id: str | None = None
    requests_completed: int = 0
    started_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    #: True after we pushed a synthetic error for unexpected thread exit.
    dead_failure_routed: bool = False

    def is_alive(self) -> bool:
        """Check if the thread is still running."""
        return self.thread.is_alive()

    def mark_idle(self) -> None:
        """Mark worker as idle after request completion."""
        self.status = WorkerThreadStatus.IDLE
        self.current_loop_id = None
        self.current_request_id = None
        self.last_activity = datetime.now()

    def mark_busy(self, loop_id: str, request_id: str) -> None:
        """Mark worker as busy handling a request."""
        self.status = WorkerThreadStatus.BUSY
        self.current_loop_id = loop_id
        self.current_request_id = request_id
        self.last_activity = datetime.now()


@dataclass
class ThreadPoolMetrics:
    """Thread pool utilization and performance metrics."""

    total_threads: int
    idle_threads: int
    busy_threads: int
    dead_threads: int
    total_requests_completed: int
    requests_in_progress: int
    avg_request_latency_ms: float = 0.0
    thread_uptimes: dict[str, float] = field(default_factory=dict)
    dispatch_waiters_waiting: int = 0


def _thread_worker_body(
    config: SootheConfig,
    worker_id: str,
    request_queue: queue.Queue,
    response_queue: queue.Queue,
    cancel_event: threading.Event,
    stop_event: threading.Event,
    idle_timeout_seconds: int,
    max_requests: int,
    default_timeout_seconds: int,
    *,
    is_baseline_worker: bool = True,
    identity_runtime: IdentityRuntime | None = None,
    reuse_runner: bool = True,
    warmup_runner: bool = True,
    warmup_core_agent: bool = True,
    warmup_done_event: threading.Event | None = None,
) -> None:
    """Thread worker body: maintains event loop, executes requests.

    Behavior:
        - Creates dedicated asyncio event loop at startup
        - Wait for requests on request_queue (with idle timeout)
        - Reuse one SootheRunner per worker when ``reuse_runner`` (IG-506)
        - Execute request, stream results to response_queue
        - Check cancel_event between chunks for cooperative cancellation
        - Exit on stop_event, idle timeout (scaled workers only), or max requests

    Args:
        config: SootheConfig (shared memory, no pickling needed).
        worker_id: Unique worker identifier for logging.
        request_queue: threading.Queue for receiving requests.
        response_queue: threading.Queue for sending responses.
        cancel_event: threading.Event for cooperative cancellation.
        stop_event: threading.Event for shutdown signal.
        idle_timeout_seconds: Exit after this many seconds idle (scaled workers only).
        max_requests: Exit after this many requests completed.
        default_timeout_seconds: Default per-request timeout if not specified.
        is_baseline_worker: When True, wait indefinitely for work (min pool slot).
    """
    # Create dedicated event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    requests_completed = 0
    cached_runner = None

    try:
        from soothe_daemon.runner._worker_runner import warmup_worker_runner_on_loop

        cached_runner = warmup_worker_runner_on_loop(
            loop,
            config=config,
            reuse_runner=reuse_runner,
            warmup_runner=warmup_runner,
            warmup_core_agent=warmup_core_agent,
            identity_runtime=identity_runtime,
            worker_id=worker_id,
        )
    finally:
        if warmup_done_event is not None:
            warmup_done_event.set()

    def _run_single(req: LoopRunRequest, request_id: str, pusher: ResponsePusher | None) -> None:
        """Execute one request, reusing worker runner when configured."""
        from soothe.runner._worker_utils import cancel_orphan_loop_tasks
        from soothe.runner.worker_logging import configure_loop_runner_worker_logging

        from soothe_daemon.runner._worker_runner import acquire_worker_runner

        def _emit(msg_type: str, payload: Any = None) -> None:
            if pusher is not None:
                pusher.push_from_worker(msg_type, payload)
            else:
                response_queue.put((msg_type, request_id, payload))

        configure_loop_runner_worker_logging(config, req.loop_id)
        cancel_event.clear()

        # Determine timeout: use request-specific or default
        timeout_seconds = (
            req.timeout_seconds
            if req.timeout_seconds and req.timeout_seconds > 0
            else default_timeout_seconds
        )
        timeout_enabled = timeout_seconds > 0

        async def _execute() -> None:
            nonlocal cached_runner
            runner = None

            try:
                runner, cached_runner = acquire_worker_runner(
                    config=config,
                    cached_runner=cached_runner,
                    reuse_runner=reuse_runner,
                    warmup_runner=False,
                    identity_runtime=identity_runtime,
                )

                timeout_ctx = asyncio.timeout(timeout_seconds) if timeout_enabled else None

                async def _stream() -> None:
                    async for chunk in runner.astream(
                        req.user_input,
                        thread_id=req.thread_id,
                        workspace=req.resolve_workspace_path(),
                        max_iterations=req.max_iterations,
                        preferred_subagent=req.preferred_subagent,
                        client_loop_id=req.loop_id,
                        autopilot_job=req.autopilot_job,  # RFC-222 revised
                        clarification_mode=req.clarification_mode,
                        clarification_answer=req.clarification_answer,
                        clarification_answers=req.clarification_answers,
                    ):
                        # COOPERATIVE CANCELLATION: Check cancel_event between chunks
                        if cancel_event.is_set():
                            logger.info(
                                "Thread worker %s: cancellation requested for loop=%s request_id=%s",
                                worker_id,
                                req.loop_id,
                                request_id,
                            )
                            _emit("cancelled")
                            return

                        _emit("chunk", chunk)

                    _emit("done")

                async def _stream_with_cancel_poll() -> None:
                    stream_task = asyncio.create_task(_stream())

                    async def _poll_cancel_event() -> None:
                        """Cancel stream when cancel_event is set."""
                        try:
                            while True:
                                await asyncio.sleep(0.25)
                                if cancel_event.is_set():
                                    stream_task.cancel()
                                    return
                        except asyncio.CancelledError:
                            raise

                    poll_task = asyncio.create_task(_poll_cancel_event())
                    try:
                        await stream_task
                    finally:
                        poll_task.cancel()
                        try:
                            await poll_task
                        except asyncio.CancelledError:
                            pass

                if timeout_ctx:
                    async with timeout_ctx:
                        await _stream_with_cancel_poll()
                else:
                    await _stream_with_cancel_poll()

            except asyncio.CancelledError:
                logger.warning(
                    "Thread worker %s: asyncio.CancelledError loop=%s request_id=%s",
                    worker_id,
                    req.loop_id,
                    request_id,
                )
                _emit("cancelled")
            except TimeoutError:
                logger.warning(
                    "Thread worker %s: request timeout (%ds) loop=%s request_id=%s",
                    worker_id,
                    timeout_seconds,
                    req.loop_id,
                    request_id,
                )
                _emit(
                    "timeout",
                    RuntimeError(f"Request exceeded {timeout_seconds}s timeout"),
                )
            except Exception as exc:
                _record_worker_last_error(worker_id, exc)
                _emit("error", exc)
            finally:
                if runner is not None:
                    try:
                        if reuse_runner:
                            runner.prepare_for_request()
                        else:
                            await runner.cleanup()
                    except asyncio.CancelledError:
                        logger.debug(
                            "Thread worker %s: runner cleanup cancelled loop=%s request_id=%s",
                            worker_id,
                            req.loop_id,
                            request_id,
                        )
                    except Exception:
                        logger.debug(
                            "Thread worker %s: runner cleanup failed loop=%s request_id=%s",
                            worker_id,
                            req.loop_id,
                            request_id,
                            exc_info=True,
                        )

        try:
            loop.run_until_complete(_execute())
        except asyncio.CancelledError:
            logger.warning(
                "Thread worker %s: run_until_complete CancelledError loop=%s request_id=%s",
                worker_id,
                req.loop_id,
                request_id,
            )
            try:
                _emit("cancelled")
            except Exception:
                logger.exception(
                    "Thread worker %s: failed to enqueue cancelled request_id=%s",
                    worker_id,
                    request_id,
                )
        except Exception as exc:
            logger.exception(
                "Thread worker %s: uncaught exception loop=%s request_id=%s",
                worker_id,
                req.loop_id,
                request_id,
            )
            _record_worker_last_error(worker_id, exc)
            try:
                _emit("error", exc)
            except Exception:
                logger.exception(
                    "Thread worker %s: failed to enqueue error request_id=%s",
                    worker_id,
                    request_id,
                )
        finally:
            cancel_orphan_loop_tasks(loop)
            _emit("ready")

    try:
        while not stop_event.is_set() and requests_completed < max_requests:
            try:
                if is_baseline_worker:
                    msg = request_queue.get(timeout=1.0)
                else:
                    msg = request_queue.get(timeout=idle_timeout_seconds)
            except queue.Empty:
                if is_baseline_worker:
                    continue
                logger.info(
                    "Thread worker %s idle timeout (%ds), exiting",
                    worker_id,
                    idle_timeout_seconds,
                )
                break

            if msg is None:
                # Shutdown sentinel
                logger.info("Thread worker %s received shutdown signal, exiting", worker_id)
                break

            # Parse: ("request", request_id, LoopRunRequest[, ResponsePusher])
            msg_type = msg[0]
            if msg_type != "request":
                logger.warning(
                    "Thread worker %s received unexpected message type: %s",
                    worker_id,
                    msg_type,
                )
                continue

            request_id = msg[1]
            req = msg[2]
            pusher = msg[3] if len(msg) > 3 else None

            logger.debug(
                "Thread worker %s starting request loop=%s request_id=%s",
                worker_id,
                req.loop_id,
                request_id,
            )
            _run_single(req, request_id, pusher)
            requests_completed += 1
            logger.debug(
                "Thread worker %s completed request %d/%d loop=%s request_id=%s",
                worker_id,
                requests_completed,
                max_requests,
                req.loop_id,
                request_id,
            )

    finally:
        loop.close()
        logger.info("Thread worker %s exiting after %d requests", worker_id, requests_completed)


class ThreadPool:
    """Singleton pool of worker threads for loop execution.

    Pre-warms N worker threads at daemon startup. Each thread has:
        - Dedicated asyncio event loop (threads cannot share loops)
        - request_queue for receiving requests from main
        - response_queue for sending responses back
        - cancel_event for cooperative cancellation

    Workers reuse one SootheRunner per thread (IG-506) and stream results tagged
    with request_id for routing to the correct pending request.

    Lifecycle:
        - Startup: pre-warm min_pool_size baseline threads (no idle timeout)
        - Runtime: threads pull requests, execute, return to pool
        - Scaling: spawn extra threads when needed; scaled threads idle out and shrink
        - Shutdown: signal all threads to exit, wait, cleanup
    """

    _shared_pool: ThreadPool | None = None
    _pool_lock: asyncio.Lock | None = None

    def __init__(
        self,
        config: SootheConfig,
        min_pool_size: int = 2,
        max_pool_size: int = 8,
        idle_timeout_seconds: int = 300,
        max_requests_per_thread: int = 100,
        request_timeout_seconds: int = 0,
        thread_startup_timeout_seconds: int = 10,
        *,
        identity_runtime: IdentityRuntime | None = None,
        reuse_runner: bool = True,
        warmup_runner: bool = True,
        warmup_core_agent: bool = True,
    ) -> None:
        self._config = config  # Shared memory, no spawn-safe copy needed
        self._identity_runtime = identity_runtime
        self._reuse_runner = reuse_runner
        self._warmup_runner = warmup_runner
        self._warmup_core_agent = warmup_core_agent
        self._min_pool_size = min_pool_size
        self._max_pool_size = max(min_pool_size, max_pool_size)
        self._idle_timeout_seconds = idle_timeout_seconds
        self._max_requests_per_thread = max_requests_per_thread
        self._request_timeout_seconds = request_timeout_seconds
        self._thread_startup_timeout_seconds = thread_startup_timeout_seconds

        self._workers: dict[str, WorkerThreadState] = {}
        self._workers_by_loop_id: dict[str, str] = {}
        self._dispatch_semaphore: asyncio.Semaphore | None = None
        self._worker_available: asyncio.Condition | None = None
        self._waiting_for_worker_slot: int = 0
        self._running = False
        self._metrics_requests_total = 0
        # Bounded to prevent memory leak - only need last 100 for avg calculation
        self._metrics_latencies: list[float] = []
        self._pending_responses: dict[str, asyncio.Queue] = {}
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._health_task: asyncio.Task | None = None
        self._abandon_drain_tasks: set[asyncio.Task[None]] = set()
        self._next_worker_index: int = 0

    @classmethod
    async def get_shared_instance(
        cls,
        config: SootheConfig,
        daemon_config: SootheDaemonConfig,
        *,
        identity_runtime: IdentityRuntime | None = None,
    ) -> ThreadPool:
        """Get or create the singleton pool instance."""
        if cls._shared_pool is not None:
            return cls._shared_pool

        if cls._pool_lock is None:
            cls._pool_lock = asyncio.Lock()

        async with cls._pool_lock:
            if cls._shared_pool is not None:
                return cls._shared_pool

            pool_config = daemon_config.thread_pool
            pool = ThreadPool(
                config=config,
                min_pool_size=pool_config.min_pool_size,
                max_pool_size=pool_config.get_effective_pool_size(),
                idle_timeout_seconds=pool_config.idle_timeout_seconds,
                max_requests_per_thread=pool_config.max_requests_per_thread,
                request_timeout_seconds=pool_config.request_timeout_seconds,
                thread_startup_timeout_seconds=pool_config.thread_startup_timeout_seconds,
                identity_runtime=identity_runtime,
                reuse_runner=pool_config.reuse_runner,
                warmup_runner=pool_config.warmup_runner,
                warmup_core_agent=pool_config.warmup_core_agent,
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
        """Pre-warm min_pool_size worker threads."""
        self._dispatch_semaphore = asyncio.Semaphore(self._max_pool_size)
        self._worker_available = asyncio.Condition()

        warmup_events: list[threading.Event] = []
        for i in range(self._min_pool_size):
            worker_id = f"thread-worker-{i}"
            _, warmup_event = await self._spawn_worker(
                worker_id,
                is_baseline=True,
            )
            warmup_events.append(warmup_event)
            self._next_worker_index = i + 1

        await self._wait_for_worker_warmups(warmup_events)

        self._running = True
        self._main_loop = asyncio.get_running_loop()
        self._health_task = asyncio.create_task(self._worker_health_watchdog())

        logger.info(
            "ThreadPool: pre-warmed %d threads (min=%d, max=%d, idle_timeout=%ds, max_requests=%d)",
            self._min_pool_size,
            self._min_pool_size,
            self._max_pool_size,
            self._idle_timeout_seconds,
            self._max_requests_per_thread,
        )
        # IG-534: Guidance for thread pool sizing relative to concurrent loops
        if self._max_pool_size < 4:
            logger.warning(
                "ThreadPool: max_pool_size=%d is small; recommend ≥4 for multi-loop workloads "
                "(each concurrent synthesis occupies one thread for the full turn)",
                self._max_pool_size,
            )

    async def _wait_for_worker_warmups(self, events: list[threading.Event]) -> None:
        """Block until baseline workers finish SootheRunner/CoreAgent warmup."""
        if not events:
            return

        loop = asyncio.get_running_loop()
        timeout = self._thread_startup_timeout_seconds

        async def _wait_all() -> None:
            await asyncio.gather(*(loop.run_in_executor(None, event.wait) for event in events))

        try:
            await asyncio.wait_for(_wait_all(), timeout=timeout)
        except TimeoutError:
            pending = sum(1 for event in events if not event.is_set())
            logger.warning(
                "ThreadPool: %d/%d baseline workers still warming after %ds",
                pending,
                len(events),
                timeout,
            )

    async def _spawn_worker(
        self,
        worker_id: str,
        *,
        is_baseline: bool = True,
    ) -> tuple[WorkerThreadState, threading.Event]:
        """Spawn a single worker thread with queues and events."""
        request_queue: queue.Queue = queue.Queue()
        response_queue: queue.Queue = queue.Queue(maxsize=_RESPONSE_QUEUE_MAXSIZE)
        cancel_event: threading.Event = threading.Event()
        stop_event: threading.Event = threading.Event()
        warmup_done_event = threading.Event()

        thread = threading.Thread(
            target=_thread_worker_body,
            args=(
                self._config,
                worker_id,
                request_queue,
                response_queue,
                cancel_event,
                stop_event,
                self._idle_timeout_seconds,
                self._max_requests_per_thread,
                self._request_timeout_seconds,
            ),
            kwargs={
                "is_baseline_worker": is_baseline,
                "identity_runtime": self._identity_runtime,
                "reuse_runner": self._reuse_runner,
                "warmup_runner": self._warmup_runner,
                "warmup_core_agent": self._warmup_core_agent,
                "warmup_done_event": warmup_done_event,
            },
            daemon=True,
            name=worker_id,
        )
        thread.start()

        if not (self._reuse_runner and self._warmup_runner):
            warmup_done_event.set()

        worker = WorkerThreadState(
            thread=thread,
            request_queue=request_queue,
            response_queue=response_queue,
            cancel_event=cancel_event,
            stop_event=stop_event,
            worker_id=worker_id,
            is_baseline=is_baseline,
            started_at=datetime.now(),
        )
        self._workers[worker_id] = worker

        logger.debug(
            "ThreadPool: spawned thread worker %s (baseline=%s)",
            worker_id,
            is_baseline,
        )
        return worker, warmup_done_event

    def _schedule_abandon_drain(
        self,
        worker: WorkerThreadState,
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
                    "ThreadPool: abandon drain failed worker=%s request_id=%s",
                    worker.worker_id,
                    request_id,
                )
                await self._mark_worker_idle_and_notify(worker)
                self._workers_by_loop_id.pop(loop_id, None)
                self._pending_responses.pop(request_id, None)

        task = asyncio.create_task(_run(), name=f"thread-abandon-{request_id}")
        self._abandon_drain_tasks.add(task)
        task.add_done_callback(self._abandon_drain_tasks.discard)

    async def _drain_abandoned_request(
        self,
        worker: WorkerThreadState,
        loop_id: str,
        request_id: str,
        response_queue: asyncio.Queue,
    ) -> None:
        """Consume stream after the client left; release worker when complete."""
        chunks_discarded = 0
        saw_terminal = False
        try:
            while True:
                msg_type, payload = await response_queue.get()
                if msg_type == "chunk":
                    chunks_discarded += 1
                    continue
                if msg_type in _TERMINAL_RESPONSE_TYPES:
                    saw_terminal = True
                    worker.status = WorkerThreadStatus.CLEANING_UP
                    logger.info(
                        "ThreadPool: client disconnected; worker %s request %s ended with "
                        "%s after %d undelivered chunk(s)",
                        worker.worker_id,
                        request_id,
                        msg_type,
                        chunks_discarded,
                    )
                    continue
                if msg_type == "ready":
                    return
                break
        finally:
            if saw_terminal:
                worker.requests_completed += 1
            await self._mark_worker_idle_and_notify(worker)
            self._workers_by_loop_id.pop(loop_id, None)
            self._pending_responses.pop(request_id, None)

    async def _recover_stale_busy_worker(
        self,
        worker: WorkerThreadState,
        *,
        last_error: str | None = None,
    ) -> bool:
        """Recover when a worker exited cleanly but main never received ``done``.

        Typical when the worker thread finishes while ``ThreadPool.submit()`` is
        still waiting on the response queue (crash, forced exit, or delivery gap).

        Returns:
            True if recovery ran (synthetic ``done`` or stale bookkeeping cleared)
            and the caller should skip the generic dead-worker error path.
        """
        req_id = worker.current_request_id
        if req_id is None or worker.dead_failure_routed:
            return False

        aio_q = self._pending_responses.get(req_id)
        if aio_q is None:
            if worker.status == WorkerThreadStatus.BUSY:
                logger.warning(
                    "ThreadPool: worker %s died with stale busy state and no waiter; "
                    "clearing bookkeeping (loop_id=%s, request_id=%s)",
                    worker.worker_id,
                    worker.current_loop_id,
                    req_id,
                )
                await self._mark_worker_idle_and_notify(worker)
                if worker.current_loop_id:
                    self._workers_by_loop_id.pop(worker.current_loop_id, None)
            return True

        if last_error is None:
            last_error = _pop_worker_last_error(worker.worker_id)
        if last_error is not None:
            return False

        worker.dead_failure_routed = True
        try:
            await aio_q.put(("done", None))
            await aio_q.put(("ready", None))
            logger.warning(
                "ThreadPool: worker %s died with stale busy state; delivered recovery "
                "done (loop_id=%s, request_id=%s)",
                worker.worker_id,
                worker.current_loop_id,
                req_id,
            )
        except Exception:
            worker.dead_failure_routed = False
            logger.exception(
                "ThreadPool: failed to deliver recovery done request_id=%s",
                req_id,
            )
            return False

        await self._mark_worker_idle_and_notify(worker)
        if worker.current_loop_id:
            self._workers_by_loop_id.pop(worker.current_loop_id, None)
        self._pending_responses.pop(req_id, None)
        return True

    async def _route_failure_for_dead_busy_worker(self, worker: WorkerThreadState) -> None:
        """If a worker thread died while handling a request, unblock the waiter with error."""
        req_id = worker.current_request_id
        if req_id is None or worker.dead_failure_routed:
            return

        aio_q = self._pending_responses.get(req_id)
        if aio_q is None:
            logger.warning(
                "ThreadPool: worker %s died busy but no pending route request_id=%s",
                worker.worker_id,
                req_id,
            )
            worker.dead_failure_routed = True
            return

        worker.dead_failure_routed = True
        err = RuntimeError(
            "Worker thread exited unexpectedly during query execution; "
            "check daemon logs for errors."
        )
        try:
            await aio_q.put(("error", err))
            await aio_q.put(("ready", None))
        except Exception:
            worker.dead_failure_routed = False
            logger.exception(
                "ThreadPool: failed to deliver dead-worker error request_id=%s",
                req_id,
            )

    def _count_live_workers(self) -> int:
        return sum(1 for w in self._workers.values() if w.is_alive())

    async def _remove_worker_slot(self, worker: WorkerThreadState) -> None:
        """Drop a dead worker entry without respawning (scale-down)."""
        self._workers.pop(worker.worker_id, None)
        await self._notify_worker_slot_available()

    async def _handle_dead_worker(self, worker: WorkerThreadState) -> None:
        """Recover from a dead thread: shrink scaled slots or respawn baseline/min."""
        last_err = _pop_worker_last_error(worker.worker_id)
        graceful_idle_exit = (
            worker.status == WorkerThreadStatus.IDLE
            and worker.current_request_id is None
            and last_err is None
        )

        if graceful_idle_exit and not worker.is_baseline:
            logger.info(
                "ThreadPool: scaled worker %s idle timeout, removing slot (live=%d, min=%d)",
                worker.worker_id,
                self._count_live_workers(),
                self._min_pool_size,
            )
            await self._remove_worker_slot(worker)
            return

        if worker.current_request_id is not None:
            logger.warning(
                "ThreadPool: worker %s thread ended (busy=%s, loop_id=%s, "
                "request_id=%s, status=%s%s)",
                worker.worker_id,
                worker.status == WorkerThreadStatus.BUSY,
                worker.current_loop_id,
                worker.current_request_id,
                worker.status,
                f", last_error={last_err!r}" if last_err else "",
            )
            recovered = await self._recover_stale_busy_worker(worker, last_error=last_err)
            if not recovered:
                await self._route_failure_for_dead_busy_worker(worker)
        elif not graceful_idle_exit:
            logger.warning(
                "ThreadPool: worker %s thread ended unexpectedly (status=%s%s)",
                worker.worker_id,
                worker.status,
                f", last_error={last_err!r}" if last_err else "",
            )

        try:
            await self._respawn_worker(worker, is_baseline=worker.is_baseline)
        except Exception:
            logger.exception("ThreadPool: failed to respawn dead worker %s", worker.worker_id)

    async def _worker_health_watchdog(self) -> None:
        """Dead-worker recovery and idle stale-queue drain (no chunk relay; IG-429)."""
        loop = asyncio.get_event_loop()

        while self._running:
            for worker_id, worker in list(self._workers.items()):
                if not worker.is_alive():
                    await self._handle_dead_worker(worker)
                    continue

                if worker.current_request_id is not None:
                    continue

                drained = 0
                while True:
                    try:
                        await loop.run_in_executor(
                            None,
                            worker.response_queue.get_nowait,
                        )
                    except queue.Empty:
                        break
                    drained += 1
                if drained:
                    logger.debug(
                        "ThreadPool: drained %d stale response(s) from idle worker %s",
                        drained,
                        worker_id,
                    )

            await asyncio.sleep(1.0)

    async def _respawn_worker(
        self,
        dead_worker: WorkerThreadState,
        *,
        is_baseline: bool | None = None,
    ) -> None:
        """Replace a dead worker with a fresh one."""
        baseline = dead_worker.is_baseline if is_baseline is None else is_baseline
        logger.warning(
            "ThreadPool: respawning worker %s (baseline=%s, live=%d, min=%d)",
            dead_worker.worker_id,
            baseline,
            self._count_live_workers(),
            self._min_pool_size,
        )

        new_worker, _ = await self._spawn_worker(dead_worker.worker_id, is_baseline=baseline)
        self._workers[dead_worker.worker_id] = new_worker
        await self._notify_worker_slot_available()

    async def _notify_worker_slot_available(self) -> None:
        cond = self._worker_available
        if cond is None:
            return
        async with cond:
            cond.notify_all()

    async def _mark_worker_idle_and_notify(self, worker: WorkerThreadState) -> None:
        worker.mark_idle()
        await self._notify_worker_slot_available()

    async def _await_worker_ready(self, response_queue: asyncio.Queue[Any]) -> None:
        """Block until the worker finishes post-run cleanup."""
        while True:
            msg_type, _payload = await response_queue.get()
            if msg_type == "ready":
                return
            if msg_type == "chunk":
                logger.debug("ThreadPool: discarding stray chunk while awaiting worker ready")
                continue
            logger.warning(
                "ThreadPool: unexpected %s while awaiting worker ready",
                msg_type,
            )

    async def _finish_request_after_terminal(
        self,
        worker: WorkerThreadState,
        loop_id: str,
        request_id: str,
        response_queue: asyncio.Queue[Any],
        *,
        start_time: datetime,
    ) -> None:
        """Release worker only after cleanup completes (``ready`` signal)."""
        worker.status = WorkerThreadStatus.CLEANING_UP
        await self._await_worker_ready(response_queue)
        await self._mark_worker_idle_and_notify(worker)
        self._workers_by_loop_id.pop(loop_id, None)
        self._pending_responses.pop(request_id, None)
        self._metrics_requests_total += 1
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        self._metrics_latencies.append(latency_ms)
        if len(self._metrics_latencies) > 100:
            self._metrics_latencies = self._metrics_latencies[-100:]
        worker.requests_completed += 1

    def _worker_pool_counts(self) -> tuple[int, int]:
        """Return (idle, busy) live worker counts for dispatch diagnostics."""
        idle = sum(
            1
            for w in self._workers.values()
            if w.status == WorkerThreadStatus.IDLE and w.is_alive()
        )
        busy = sum(
            1
            for w in self._workers.values()
            if w.status in (WorkerThreadStatus.BUSY, WorkerThreadStatus.CLEANING_UP)
        )
        return idle, busy

    async def _try_acquire_idle_worker(self) -> WorkerThreadState | None:
        """Return an idle live worker, scale up, or respawn a dead slot."""
        for w in self._workers.values():
            if w.status == WorkerThreadStatus.IDLE and w.is_alive():
                return w

        active_count = sum(1 for w in self._workers.values() if w.is_alive())
        if active_count < self._max_pool_size:
            worker_id = f"thread-worker-{self._next_worker_index}"
            self._next_worker_index += 1
            logger.info(
                "ThreadPool: scaling up, spawning extra worker %s (active=%d, max=%d)",
                worker_id,
                active_count + 1,
                self._max_pool_size,
            )
            worker, _ = await self._spawn_worker(worker_id, is_baseline=False)
            return worker

        for w in self._workers.values():
            if w.status == WorkerThreadStatus.DEAD or not w.is_alive():
                await self._handle_dead_worker(w)
                replacement = self._workers.get(w.worker_id)
                if replacement is not None and replacement.is_alive():
                    return replacement
                continue

        return None

    async def submit(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Submit request to pool, await available worker, stream results."""
        request_id = uuid.uuid4().hex[:16]

        if request.timeout_seconds is None or request.timeout_seconds <= 0:
            request.timeout_seconds = (
                self._request_timeout_seconds if self._request_timeout_seconds > 0 else None
            )

        async with self._dispatch_semaphore:
            cond = self._worker_available
            if cond is None:
                raise RuntimeError("ThreadPool is not started")

            worker: WorkerThreadState
            response_queue: asyncio.Queue
            handoff_retries = 0
            dispatch_wait_logged = False
            dispatch_wait_started: float | None = None
            while True:
                while True:
                    worker = await self._try_acquire_idle_worker()
                    if worker is not None:
                        break
                    if not self._running:
                        raise RuntimeError("ThreadPool is shutting down")
                    now = asyncio.get_running_loop().time()
                    if dispatch_wait_started is None:
                        dispatch_wait_started = now
                        idle, busy = self._worker_pool_counts()
                        logger.warning(
                            "ThreadPool: waiting for idle worker loop=%s request_id=%s "
                            "idle=%d busy=%d waiters=%d",
                            request.loop_id,
                            request_id,
                            idle,
                            busy,
                            self._waiting_for_worker_slot + 1,
                        )
                        dispatch_wait_logged = True
                    elif dispatch_wait_logged and now - dispatch_wait_started >= 30.0:
                        idle, busy = self._worker_pool_counts()
                        logger.warning(
                            "ThreadPool: still waiting for idle worker loop=%s request_id=%s "
                            "idle=%d busy=%d waiters=%d elapsed=%.0fs",
                            request.loop_id,
                            request_id,
                            idle,
                            busy,
                            self._waiting_for_worker_slot + 1,
                            now - dispatch_wait_started,
                        )
                        dispatch_wait_started = now
                    async with cond:
                        self._waiting_for_worker_slot += 1
                        try:
                            await cond.wait()
                        finally:
                            self._waiting_for_worker_slot -= 1

                # IG-477: Bound response queue to prevent memory leak
                response_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=_RESPONSE_QUEUE_MAXSIZE)
                self._pending_responses[request_id] = response_queue
                self._workers_by_loop_id[request.loop_id] = worker.worker_id
                worker.mark_busy(request.loop_id, request_id)
                main_loop = self._main_loop or asyncio.get_running_loop()
                pusher = ResponsePusher(main_loop, response_queue, worker_id=worker.worker_id)
                worker.request_queue.put(("request", request_id, request, pusher))
                logger.info(
                    "ThreadPool: dispatched loop=%s request_id=%s worker=%s",
                    request.loop_id,
                    request_id,
                    worker.worker_id,
                )
                if worker.is_alive():
                    break

                # Worker exited after we observed it idle
                self._pending_responses.pop(request_id, None)
                self._workers_by_loop_id.pop(request.loop_id, None)
                worker.mark_idle()
                handoff_retries += 1
                if handoff_retries > 64:
                    raise RuntimeError(
                        "ThreadPool: unable to hand off request after repeated worker exits"
                    )
                logger.info(
                    "ThreadPool: worker %s exited during dispatch handoff; recovering",
                    worker.worker_id,
                )
                await self._handle_dead_worker(worker)

        start_time = datetime.now()
        stream_complete = False
        error_payload: BaseException | None = None

        try:
            while True:
                msg_type, payload = await response_queue.get()

                if msg_type in _TERMINAL_RESPONSE_TYPES:
                    stream_complete = True
                    if msg_type == "error":
                        error_payload = (
                            payload
                            if isinstance(payload, BaseException)
                            else RuntimeError(str(payload))
                        )
                    elif msg_type in ("timeout", "cancelled") and isinstance(
                        payload, BaseException
                    ):
                        error_payload = payload
                    break

                yield payload
        except asyncio.CancelledError:
            logger.info("ThreadPool request %s cancelled by client disconnect", request_id)
            raise
        finally:
            if stream_complete:
                await self._finish_request_after_terminal(
                    worker,
                    request.loop_id,
                    request_id,
                    response_queue,
                    start_time=start_time,
                )
            else:
                self._schedule_abandon_drain(worker, request.loop_id, request_id, response_queue)

        if error_payload is not None:
            raise error_payload

    async def cancel_request(self, loop_id: str) -> None:
        """Signal cooperative cancellation to worker handling this loop_id."""
        worker_id = self._workers_by_loop_id.get(loop_id)
        if worker_id is None:
            logger.debug("ThreadPool: no active request for loop_id=%s", loop_id)
            return

        worker = self._workers.get(worker_id)
        if worker is None:
            logger.debug("ThreadPool: worker %s not found for loop_id=%s", worker_id, loop_id)
            return

        worker.cancel_event.set()
        logger.info(
            "ThreadPool: cancellation signal sent for loop_id=%s to worker=%s",
            loop_id,
            worker_id,
        )

    async def force_cancel_worker(self, worker_id: str, timeout: float = 10.0) -> None:
        """Force cancel a worker thread after cooperative cancel fails.

        Note: Python threads cannot be forcefully killed like processes.
        This sets stop_event and marks the worker as DEAD. The poll task
        will handle cleanup on the next iteration.

        Args:
            worker_id: Worker thread to cancel.
            timeout: Seconds to wait for thread self-termination.
        """
        worker = self._workers.get(worker_id)
        if worker is None:
            logger.debug("force_cancel_worker: worker %s not found", worker_id)
            return

        if not worker.thread.is_alive():
            # Already dead - cleanup bookkeeping
            logger.debug("force_cancel_worker: worker %s already dead, cleaning up", worker_id)
            self._workers.pop(worker_id, None)
            loop_id = worker.current_loop_id or ""
            self._workers_by_loop_id.pop(loop_id, None)
            self._pending_responses.pop(worker.current_request_id or "", None)
            return

        logger.warning(
            "Force cancel thread worker %s (loop_id=%s)",
            worker_id,
            worker.current_loop_id,
        )
        worker.status = WorkerThreadStatus.SHUTTING_DOWN
        worker.stop_event.set()

        loop = asyncio.get_event_loop()

        # Wait briefly for thread to self-terminate
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, lambda: worker.thread.join(timeout=timeout)),
                timeout=timeout + 1,
            )
        except TimeoutError:
            logger.warning(
                "Thread worker %s did not self-terminate, marking as dead",
                worker_id,
            )

        # Mark as dead (poll task handles cleanup)
        worker.status = WorkerThreadStatus.DEAD
        loop_id = worker.current_loop_id or ""
        self._workers_by_loop_id.pop(loop_id, None)
        self._pending_responses.pop(worker.current_request_id or "", None)

        logger.info("Thread worker %s force cancelled", worker_id)

    def get_worker_id_for_loop(self, loop_id: str) -> str | None:
        """Return worker_id handling the given loop_id, if any."""
        return self._workers_by_loop_id.get(loop_id)

    def is_worker_idle(self, worker_id: str) -> bool:
        """Check if worker has returned to idle state."""
        worker = self._workers.get(worker_id)
        if worker is None:
            return True  # Gone means cancelled
        return worker.status == WorkerThreadStatus.IDLE or not worker.thread.is_alive()

    async def shutdown(self) -> None:
        """Graceful shutdown: signal threads, wait, cleanup."""
        self._running = False

        await self._notify_worker_slot_available()

        if self._health_task is not None:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None

        for t in list(self._abandon_drain_tasks):
            t.cancel()
        for t in list(self._abandon_drain_tasks):
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._abandon_drain_tasks.clear()

        logger.info("ThreadPool: shutting down %d workers", len(self._workers))

        # Send shutdown sentinel to all workers
        for worker in self._workers.values():
            if worker.is_alive():
                worker.request_queue.put(None)
                worker.status = WorkerThreadStatus.SHUTTING_DOWN

        # Wait for graceful exit
        for worker in self._workers.values():
            if worker.thread.is_alive():
                worker.thread.join(timeout=5)

        self._workers.clear()
        self._workers_by_loop_id.clear()
        self._pending_responses.clear()
        logger.info("ThreadPool: shutdown complete")

    def get_metrics(self) -> ThreadPoolMetrics:
        """Return pool utilization and performance metrics."""
        idle = sum(1 for w in self._workers.values() if w.status == WorkerThreadStatus.IDLE)
        busy = sum(1 for w in self._workers.values() if w.status == WorkerThreadStatus.BUSY)
        dead = sum(1 for w in self._workers.values() if not w.is_alive())

        uptimes = {
            w.worker_id: (datetime.now() - w.started_at).total_seconds()
            for w in self._workers.values()
        }

        avg_latency = 0.0
        if self._metrics_latencies:
            avg_latency = sum(self._metrics_latencies[-100:]) / len(self._metrics_latencies[-100:])

        return ThreadPoolMetrics(
            total_threads=self._max_pool_size,
            idle_threads=idle,
            busy_threads=busy,
            dead_threads=dead,
            total_requests_completed=self._metrics_requests_total,
            requests_in_progress=busy,
            avg_request_latency_ms=avg_latency,
            thread_uptimes=uptimes,
            dispatch_waiters_waiting=self._waiting_for_worker_slot,
        )


class ThreadLoopRunner:
    """Runs agent loops using the thread pool.

    Implements LoopRunnerProtocol for integration with QueryEngine.
    One instance per loop_id, created by LoopRunnerFactory.
    """

    def __init__(
        self,
        loop_id: str,
        config: SootheConfig,
        daemon_config: SootheDaemonConfig,
        *,
        identity_runtime: IdentityRuntime | None = None,
    ) -> None:
        self._loop_id = loop_id
        self._config = config
        self._daemon_config = daemon_config
        self._identity_runtime = identity_runtime
        self._pool: ThreadPool | None = None

    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Delegate to shared pool, stream results."""
        pool = await ThreadPool.get_shared_instance(
            self._config,
            self._daemon_config,
            identity_runtime=self._identity_runtime,
        )
        self._pool = pool

        async for chunk in pool.submit(request):
            yield chunk

    async def cancel(self) -> None:
        """Request cancellation."""
        if self._pool is not None:
            await self._pool.cancel_request(self._loop_id)


__all__ = [
    "ThreadPool",
    "ThreadPoolMetrics",
    "ThreadLoopRunner",
    "WorkerThreadState",
    "WorkerThreadStatus",
]
