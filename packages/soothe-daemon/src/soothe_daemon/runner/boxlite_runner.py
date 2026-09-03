"""BoxLite container-based loop runner — one warm boxlite box per worker slot.

A fifth `LoopRunnerProtocol` substrate (RFC-221) selected by
`LoopRunnerFactory` when `loop_runner.runner_mode='boxlite'`. Each container
runs the same `_pool_worker_body` / `SootheRunner` code as the process pool,
but bridges stream chunks host↔container over the **boxlite exec stream**
(stdin/stdout of a long-lived `box.exec()` call) instead of
`multiprocessing.Queue`.

**Cross-platform — supported on Linux, macOS, and Windows.** Unlike
Firecracker (which requires `AF_VSOCK`, KVM, and a Linux host), BoxLite
uses the `boxlite` Python SDK (an embeddable VM runtime) and standard
networking, making it usable on any host with the `boxlite` package
installed. The module is import-safe everywhere (no `boxlite` import at
module level); `LoopRunnerFactory` validates `boxlite` importability and
`container_image` presence at construction time. The factory imports this
module lazily inside the `boxlite` branch only, so thread/process/ray/
firecracker paths never pay the import cost.
"""

from __future__ import annotations

import asyncio
import logging
import pickle
import struct
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from soothe.protocols.runner import LoopRunRequest
from soothe.runner._worker_utils import spawn_safe_config

from soothe_daemon.config import SootheDaemonConfig

if TYPE_CHECKING:
    from soothe.config.settings import SootheConfig
    from soothe.events import StreamChunk

logger = logging.getLogger(__name__)

# Frame protocol: 4-byte big-endian length prefix + payload bytes (pickled).
# The payload is the same 3-tuple convention as `response_bridge.WORKER_MSG_*`:
#   (msg_type, request_id, payload)
_FRAME_HEADER = struct.Struct("!I")
_MAX_FRAME_BYTES = 64 * 1024 * 1024  # 64 MiB safety cap

# Terminal message types (mirror pool_runner._TERMINAL_RESPONSE_TYPES).
_TERMINAL_RESPONSE_TYPES = frozenset({"done", "error", "timeout", "cancelled"})

# The guest-side worker entrypoint script. Executed inside the container via
# `box.exec()`. Reads pickled length-prefixed frames from stdin (the
# ("request", request_id, (LoopRunRequest, spawn_safe_config)) tuple),
# executes the loop, and writes pickled length-prefixed frames to stdout
# using the same (msg_type, request_id, payload) 3-tuple convention.
_WORKER_ENTRYPOINT = r"""
import sys, struct, pickle, asyncio, threading, time

def _recv_exactly(stdin, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = stdin.buffer.read(n - len(buf))
        if not chunk:
            return None if not buf else bytes(buf)
        buf.extend(chunk)
    return bytes(buf)

def _recv_frame(stdin):
    header = _recv_exactly(stdin, 4)
    if header is None:
        return None
    (length,) = struct.unpack("!I", header)
    if length == 0 or length > 64 * 1024 * 1024:
        raise ValueError(f"Invalid frame length: {length}")
    payload = _recv_exactly(stdin, length)
    if payload is None:
        return None
    return pickle.loads(payload)

def _send_frame(stdout, msg):
    payload = pickle.dumps(msg)
    stdout.buffer.write(struct.pack("!I", len(payload)))
    stdout.buffer.write(payload)
    stdout.buffer.flush()

def main():
    from soothe_daemon.runner._worker_runner import acquire_worker_runner
    from soothe.runner._worker_utils import cancel_orphan_loop_tasks
    from soothe_daemon.runner.worker_logging import configure_loop_runner_worker_logging

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    cached_runner = None

    while True:
        try:
            frame = _recv_frame(sys.stdin)
        except Exception:
            break
        if frame is None:
            break
        msg_type, request_id, payload = frame
        if msg_type == "shutdown":
            break
        if msg_type != "request":
            continue
        req, config = payload
        configure_loop_runner_worker_logging(config, req.loop_id)
        cached_runner, _ = _run_single(loop, req, request_id, config, cached_runner)

    loop.close()

def _run_single(loop, req, request_id, config, cached_runner):
    from soothe.runner._worker_utils import cancel_orphan_loop_tasks
    import asyncio as _asyncio

    def _execute():
        nonlocal cached_runner
        try:
            runner, cached_runner = acquire_worker_runner(
                config=config,
                cached_runner=cached_runner,
                reuse_runner=True,
                warmup_runner=False,
            )
            timeout_seconds = req.timeout_seconds if req.timeout_seconds and req.timeout_seconds > 0 else 0
            timeout_ctx = _asyncio.timeout(timeout_seconds) if timeout_seconds > 0 else None

            async def _stream():
                _send_frame(sys.stdout, ("heartbeat", request_id, {"elapsed_seconds": 0.0}))
                async for chunk in runner.astream(
                    req.user_input,
                    thread_id=req.thread_id,
                    workspace=req.resolve_workspace_path(),
                    preferred_subagent=req.preferred_subagent,
                    intake_scope=req.intake_scope,
                    client_loop_id=req.loop_id,
                    autopilot_job=req.autopilot_job,
                    clarification_mode=req.clarification_mode,
                    interaction_mode=req.interaction_mode,
                    clarification_answer=req.clarification_answer,
                    clarification_answers=req.clarification_answers,
                    resume_interrupted=req.resume_interrupted,
                    approved_plan_path=req.approved_plan_path,
                ):
                    try:
                        _send_frame(sys.stdout, ("chunk", request_id, chunk))
                    except Exception:
                        pass
                _send_frame(sys.stdout, ("done", request_id, None))

            if timeout_ctx:
                async with timeout_ctx:
                    loop.run_until_complete(_stream())
            else:
                loop.run_until_complete(_stream())
        except _asyncio.CancelledError:
            _send_frame(sys.stdout, ("cancelled", request_id, None))
        except TimeoutError:
            _send_frame(sys.stdout, ("timeout", request_id, RuntimeError(f"Request exceeded timeout")))
        except Exception as exc:
            _send_frame(sys.stdout, ("error", request_id, exc))
        finally:
            cancel_orphan_loop_tasks(loop)
            _send_frame(sys.stdout, ("ready", request_id, None))

    _execute()
    return cached_runner, None

if __name__ == "__main__":
    main()
"""


# ---------------------------------------------------------------------------
# Frame protocol helpers
# ---------------------------------------------------------------------------


def _pack_frame(msg: tuple[str, str, Any]) -> bytes:
    """Pack a 3-tuple into a length-prefixed pickled frame."""
    payload = pickle.dumps(msg)
    if len(payload) > _MAX_FRAME_BYTES:
        raise ValueError(f"Frame payload too large ({len(payload)} bytes > {_MAX_FRAME_BYTES})")
    return _FRAME_HEADER.pack(len(payload)) + payload


def _parse_header(header: bytes) -> int:
    """Unpack a 4-byte frame header into the payload length."""
    (length,) = _FRAME_HEADER.unpack(header)
    if length == 0 or length > _MAX_FRAME_BYTES:
        raise ValueError(f"Invalid frame length: {length}")
    return length


# ---------------------------------------------------------------------------
# Host-side exec stream bridge
# ---------------------------------------------------------------------------


class _ExecStreamBridge:
    """Host-side reader that drains boxlite exec stdout into an asyncio queue.

    The boxlite ``Execution`` object returned by ``box.exec()`` exposes
    ``stdout()`` as an async iterator of byte chunks. This bridge reads
    those chunks, reassembles length-prefixed pickled frames, and pushes
    the decoded 3-tuples into an ``asyncio.Queue``.

    Cancel = send a ``"cancel"`` frame via ``stdin().send_input()``;
    force-kill = stop the box (handled by the pool).
    """

    def __init__(
        self,
        *,
        worker_index: int,
        execution: Any,
        response_queue: asyncio.Queue,
    ) -> None:
        self._worker_index = worker_index
        self._execution = execution
        self._response_queue = response_queue
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = False
        self._stdin = None
        self._read_buf = bytearray()

    async def start_reader(self) -> None:
        """Start the background reader task after the exec begins."""
        self._reader_task = asyncio.create_task(
            self._read_loop(), name=f"boxlite-bridge-{self._worker_index}"
        )

    async def _read_loop(self) -> None:
        """Drain frames from the container exec stdout into the asyncio queue."""
        try:
            stdout = self._execution.stdout()
            if stdout is None:
                logger.error(
                    "ExecStreamBridge: exec has no stdout (worker_index=%d)",
                    self._worker_index,
                )
                return
            async for chunk in stdout:
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                self._read_buf.extend(chunk)
                # Try to decode complete frames from the buffer.
                while len(self._read_buf) >= _FRAME_HEADER.size:
                    (length,) = _FRAME_HEADER.unpack(bytes(self._read_buf[: _FRAME_HEADER.size]))
                    if length == 0 or length > _MAX_FRAME_BYTES:
                        raise ValueError(f"Invalid frame length: {length}")
                    if len(self._read_buf) < _FRAME_HEADER.size + length:
                        break  # Incomplete frame; wait for more data.
                    payload = bytes(
                        self._read_buf[_FRAME_HEADER.size : _FRAME_HEADER.size + length]
                    )
                    del self._read_buf[: _FRAME_HEADER.size + length]
                    msg = pickle.loads(payload)  # noqa: S301 — trusted internal transport
                    msg_type, request_id, msg_payload = msg
                    await self._response_queue.put((msg_type, request_id, msg_payload))
            # stdout closed — container exec ended.
        except (OSError, ValueError) as exc:
            if not self._closed:
                logger.warning(
                    "ExecStreamBridge: read error worker_index=%d: %s",
                    self._worker_index,
                    exc,
                )
        except asyncio.CancelledError:
            raise

    def send_cancel(self, request_id: str) -> None:
        """Send a cooperative cancel frame to the container via exec stdin."""
        if self._stdin is None:
            try:
                self._stdin = self._execution.stdin()
            except Exception:
                return
        if self._stdin is None or self._closed:
            return
        try:
            frame = _pack_frame(("cancel", request_id, None))
            asyncio.get_event_loop().run_in_executor(None, self._stdin.send_input, frame)
        except Exception:
            logger.debug(
                "ExecStreamBridge: cancel send failed worker_index=%d",
                self._worker_index,
            )

    def close(self) -> None:
        """Close the bridge and stop the reader."""
        self._closed = True
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()


# ---------------------------------------------------------------------------
# Worker box abstraction
# ---------------------------------------------------------------------------


@dataclass
class BoxLiteWorker:
    """One warm boxlite box + its exec stream bridge state."""

    worker_id: str
    container_index: int
    box: Any = None
    execution: Any = None
    bridge: _ExecStreamBridge | None = None
    started_at: datetime = field(default_factory=datetime.now)
    last_heartbeat_at: datetime = field(default_factory=datetime.now)
    requests_completed: int = 0
    busy_loop_id: str | None = None
    busy_request_id: str | None = None

    @property
    def is_alive(self) -> bool:
        """True when the box is still running."""
        if self.box is None:
            return False
        try:
            # boxlite Box doesn't expose a simple is_alive; check via info if needed.
            # For now, trust that the box is alive if it was started and not stopped.
            return self.box is not None
        except Exception:
            return False

    def mark_busy(self, loop_id: str, request_id: str) -> None:
        """Mark this container as executing a request."""
        self.busy_loop_id = loop_id
        self.busy_request_id = request_id

    def mark_idle(self) -> None:
        """Return this container to the idle pool."""
        self.busy_loop_id = None
        self.busy_request_id = None
        self.requests_completed += 1


# ---------------------------------------------------------------------------
# Warm container pool (singleton)
# ---------------------------------------------------------------------------


class BoxLiteWorkerPool:
    """Singleton pool of warm boxlite containers for loop execution.

    Mirrors `ProcessPool`'s shape (singleton, pre-warm, submit → async
    generator, cancel_request, force_kill_worker_by_loop_id) so
    `QueryEngine` is fully decoupled per RFC-221.

    Each container runs the configured OCI image, which contains a
    guest-side entrypoint that imports `_pool_worker_body` and speaks the
    exec stream frame protocol. `submit(request)` acquires an idle container,
    sends the `LoopRunRequest` (pickled, spawn-safe) via exec stdin, and
    returns the bridge's async generator.
    """

    _shared_pool: BoxLiteWorkerPool | None = None
    _pool_lock: asyncio.Lock | None = None

    def __init__(
        self,
        config: SootheConfig,
        daemon_config: SootheDaemonConfig,
    ) -> None:
        self._config = config
        bl = daemon_config.loop_runner.boxlite
        self._bl_config = bl
        self._min_pool_size = bl.min_pool_size
        self._max_pool_size = max(bl.min_pool_size, bl.max_pool_size)
        self._idle_timeout_seconds = bl.idle_timeout_seconds
        self._max_requests_per_worker = bl.max_requests_per_worker
        self._request_timeout_seconds = bl.request_timeout_seconds
        self._reuse_runner = bl.reuse_runner
        self._warmup_runner = bl.warmup_runner
        self._warmup_core_agent = bl.warmup_core_agent
        self._container_cpu_count = bl.container_cpu_count
        self._container_mem_mib = bl.container_mem_mib
        self._container_image = bl.container_image
        self._rootfs_path = bl.rootfs_path
        self._workspace_mount_mode = bl.workspace_mount_mode

        self._runtime: Any = None
        self._workers: dict[str, BoxLiteWorker] = {}
        self._workers_by_loop_id: dict[str, str] = {}
        self._dispatch_semaphore: asyncio.Semaphore | None = None
        self._worker_available: asyncio.Condition | None = None
        self._pending_responses: dict[str, asyncio.Queue] = {}
        self._running = False
        self._next_container_index: int = 0
        self._health_task: asyncio.Task[None] | None = None

    # -- singleton lifecycle ------------------------------------------------

    @classmethod
    async def get_shared_instance(
        cls, config: SootheConfig, daemon_config: SootheDaemonConfig
    ) -> BoxLiteWorkerPool:
        """Get or create the singleton pool instance."""
        if cls._shared_pool is not None:
            return cls._shared_pool

        if cls._pool_lock is None:
            cls._pool_lock = asyncio.Lock()

        async with cls._pool_lock:
            if cls._shared_pool is None:
                pool = cls(config, daemon_config)
                await pool._start()
                cls._shared_pool = pool
        return cls._shared_pool

    @classmethod
    async def close_shared_instance(cls) -> None:
        """Shutdown the singleton pool."""
        if cls._pool_lock is None:
            cls._pool_lock = asyncio.Lock()
        async with cls._pool_lock:
            pool = cls._shared_pool
            if pool is not None:
                await pool._stop()
                cls._shared_pool = None

    async def _start(self) -> None:
        """Pre-warm `min_pool_size` containers at daemon startup."""
        import boxlite

        self._runtime = boxlite.Boxlite.default()
        self._running = True
        self._dispatch_semaphore = asyncio.Semaphore(self._max_pool_size)
        self._worker_available = asyncio.Condition()
        logger.info(
            "BoxLiteWorkerPool: starting (min=%d, max=%d containers, cpu=%d, mem=%dMiB)",
            self._min_pool_size,
            self._max_pool_size,
            self._container_cpu_count,
            self._container_mem_mib,
        )
        for _ in range(self._min_pool_size):
            try:
                await self._spawn_warm_container()
            except Exception:
                logger.warning("BoxLiteWorkerPool: failed to pre-warm container", exc_info=True)
        self._health_task = asyncio.create_task(self._health_loop(), name="boxlite-health")

    async def _stop(self) -> None:
        """Shutdown all containers."""
        self._running = False
        if self._health_task is not None:
            self._health_task.cancel()
            try:
                await self._health_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        for worker in list(self._workers.values()):
            await self._shutdown_container(worker)
        self._workers.clear()
        self._workers_by_loop_id.clear()
        self._pending_responses.clear()
        logger.info("BoxLiteWorkerPool: stopped")

    # -- container lifecycle ------------------------------------------------

    async def _spawn_warm_container(self) -> BoxLiteWorker:
        """Start one warm boxlite container and begin the worker exec loop."""
        import boxlite

        worker_id = f"boxlite-{uuid.uuid4().hex[:8]}"
        container_index = self._next_container_index
        self._next_container_index += 1

        # Create the box via boxlite API.
        box_opts_kwargs: dict[str, Any] = {
            "cpus": self._container_cpu_count,
            "memory_mib": self._container_mem_mib,
            "auto_remove": True,
        }
        if self._rootfs_path:
            box_opts_kwargs["rootfs_path"] = self._rootfs_path
        else:
            if not self._container_image:
                raise ValueError(
                    "Container image not set. Set loop_runner.boxlite.container_image."
                )
            box_opts_kwargs["image"] = self._container_image

        box = boxlite.SimpleBox(**box_opts_kwargs, runtime=self._runtime)
        await box.start()
        logger.info(
            "BoxLiteWorkerPool: warm container %s started (box_id=%s)",
            worker_id,
            box.id,
        )

        worker = BoxLiteWorker(
            worker_id=worker_id,
            container_index=container_index,
            box=box,
        )
        self._workers[worker_id] = worker
        return worker

    async def _shutdown_container(self, worker: BoxLiteWorker) -> None:
        """Gracefully stop a boxlite container."""
        if worker.bridge is not None:
            worker.bridge.close()
        if worker.box is not None:
            try:
                await worker.box.stop()
            except Exception:  # noqa: BLE001
                logger.debug(
                    "BoxLiteWorkerPool: box stop failed for worker=%s",
                    worker.worker_id,
                    exc_info=True,
                )

    # -- dispatch -----------------------------------------------------------

    async def submit(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Acquire an idle container, send the request, stream results.

        Mirrors `ProcessPool.submit`'s structure: acquire a worker under the
        dispatch semaphore, register routing, send the request via exec stdin,
        then drain the response queue yielding chunks until a terminal frame.
        """
        request_id = uuid.uuid4().hex[:16]

        await self.await_loop_dispatchable(request.loop_id)

        if request.timeout_seconds is None or request.timeout_seconds <= 0:
            request.timeout_seconds = (
                self._request_timeout_seconds if self._request_timeout_seconds > 0 else None
            )

        assert self._dispatch_semaphore is not None
        async with self._dispatch_semaphore:
            cond = self._worker_available
            if cond is None:
                raise RuntimeError("BoxLite pool is not started")

            worker: BoxLiteWorker
            while True:
                worker = await self._try_acquire_idle_worker()
                if worker is not None:
                    break
                if not self._running:
                    raise RuntimeError("BoxLite pool is shutting down")
                async with cond:
                    await cond.wait()

            response_queue = asyncio.Queue(maxsize=100)
            self._pending_responses[request_id] = response_queue
            self._workers_by_loop_id[request.loop_id] = worker.worker_id
            worker.mark_busy(request.loop_id, request_id)

            # Start the worker exec: run the entrypoint script inside the container.
            # The script reads pickled frames from stdin and writes them to stdout.
            assert worker.box is not None
            spawn_safe = spawn_safe_config(self._config)
            execution = await worker.box._box.exec(
                "python",
                ["-c", _WORKER_ENTRYPOINT],
                env=[("SOOTHE_WORKER_ID", worker.worker_id)],
            )
            worker.execution = execution

            bridge = _ExecStreamBridge(
                worker_index=worker.container_index,
                execution=execution,
                response_queue=response_queue,
            )
            worker.bridge = bridge
            await bridge.start_reader()

            # Send the request frame via exec stdin.
            stdin = execution.stdin()
            if stdin is not None:
                frame = _pack_frame(("request", request_id, (request, spawn_safe)))
                await asyncio.get_event_loop().run_in_executor(None, stdin.send_input, frame)

        stream_complete = False
        error_payload: BaseException | None = None

        try:
            while True:
                msg_type, _req_id, payload = await response_queue.get()

                if msg_type == "heartbeat":
                    worker.last_heartbeat_at = datetime.now()
                    continue

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
                    elif msg_type == "cancelled" and error_payload is None:
                        error_payload = asyncio.CancelledError()
                    break

                # msg_type == "chunk" (or "ready" — pass through as payload)
                yield payload
        except asyncio.CancelledError:
            logger.info(
                "BoxLiteWorkerPool: request %s cancelled by client disconnect",
                request_id,
            )
            raise
        finally:
            if not stream_complete:
                self._schedule_abandon_drain(response_queue)
            self._pending_responses.pop(request_id, None)
            self._workers_by_loop_id.pop(request.loop_id, None)
            worker.mark_idle()
            cond = self._worker_available
            if cond is not None:
                async with cond:
                    cond.notify_all()

        if error_payload is not None:
            raise error_payload

    def _schedule_abandon_drain(self, response_queue: asyncio.Queue) -> None:
        """Drain remaining frames until terminal (client disconnect path)."""
        asyncio.create_task(self._drain_until_terminal(response_queue))

    async def _drain_until_terminal(self, response_queue: asyncio.Queue) -> None:
        """Drain remaining frames until done/error/cancelled (client disconnect)."""
        try:
            while True:
                msg = await asyncio.wait_for(response_queue.get(), timeout=5.0)
                if not isinstance(msg, tuple) or len(msg) != 3:
                    continue
                kind, _, _ = msg
                if kind in _TERMINAL_RESPONSE_TYPES:
                    return
        except (TimeoutError, asyncio.CancelledError):
            return

    async def _try_acquire_idle_worker(self) -> BoxLiteWorker | None:
        """Find an idle, alive container; spawn a new one if under max and none idle."""
        for worker in self._workers.values():
            if worker.busy_loop_id is None and worker.is_alive:
                return worker
        # Scale up if under max.
        if len(self._workers) < self._max_pool_size:
            try:
                return await self._spawn_warm_container()
            except Exception:  # noqa: BLE001
                logger.warning("BoxLiteWorkerPool: failed to spawn warm container", exc_info=True)
        return None

    async def await_loop_dispatchable(self, loop_id: str) -> None:
        """Wait until this loop can be dispatched (no existing busy mapping)."""
        existing = self._workers_by_loop_id.get(loop_id)
        if existing is None:
            return
        cond = self._worker_available
        if cond is None:
            return
        async with cond:
            while loop_id in self._workers_by_loop_id:
                await cond.wait()

    # -- cancel / idle / force-kill -----------------------------------------

    async def cancel_request(self, loop_id: str) -> None:
        """Send a cooperative cancel frame to the container running this loop."""
        worker_id = self._workers_by_loop_id.get(loop_id)
        if worker_id is None:
            logger.debug("BoxLiteWorkerPool: no active request for loop_id=%s", loop_id)
            return
        worker = self._workers.get(worker_id)
        if worker is None or worker.bridge is None:
            logger.debug(
                "BoxLiteWorkerPool: worker %s not found for loop_id=%s",
                worker_id,
                loop_id,
            )
            return
        if worker.busy_request_id is not None:
            worker.bridge.send_cancel(worker.busy_request_id)
        logger.info(
            "BoxLiteWorkerPool: cancel sent to container %s for loop=%s",
            worker_id,
            loop_id[:16],
        )

    def is_loop_busy(self, loop_id: str) -> bool:
        """True when a busy container is mapped to this loop's request."""
        worker_id = self._workers_by_loop_id.get(loop_id)
        if worker_id is None:
            return False
        worker = self._workers.get(worker_id)
        return worker is not None and worker.busy_loop_id == loop_id

    async def force_kill_worker_by_loop_id(self, loop_id: str, *, timeout: float = 10.0) -> None:
        """Force-shutdown the container mapped to this loop (cancel backstop)."""
        worker_id = self._workers_by_loop_id.pop(loop_id, None)
        if worker_id is None:
            return
        worker = self._workers.get(worker_id)
        if worker is None:
            return
        logger.warning(
            "BoxLiteWorkerPool: force-killing container %s for loop=%s",
            worker_id,
            loop_id[:16],
        )
        await self._shutdown_container(worker)
        self._workers.pop(worker_id, None)
        self._pending_responses.pop(worker.busy_request_id or "", None)
        # Respawn a warm container to maintain pool size.
        if self._running and len(self._workers) < self._min_pool_size:
            try:
                await self._spawn_warm_container()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "BoxLiteWorkerPool: failed to respawn container after force-kill",
                    exc_info=True,
                )
        # Wake any dispatch waiters.
        cond = self._worker_available
        if cond is not None:
            async with cond:
                cond.notify_all()

    # -- health / idle reaping ---------------------------------------------

    async def _health_loop(self) -> None:
        """Periodically reap idle/dead containers and maintain min pool size."""
        while self._running:
            await asyncio.sleep(30.0)
            now = datetime.now()
            for worker_id, worker in list(self._workers.items()):
                if worker.busy_loop_id is not None:
                    continue
                idle_seconds = (now - worker.last_heartbeat_at).total_seconds()
                if idle_seconds > self._idle_timeout_seconds:
                    logger.info(
                        "BoxLiteWorkerPool: idle container %s timed out (%.0fs); shutting down",
                        worker_id,
                        idle_seconds,
                    )
                    await self._shutdown_container(worker)
                    self._workers.pop(worker_id, None)
            # Maintain min pool size.
            while self._running and len(self._workers) < self._min_pool_size:
                try:
                    await self._spawn_warm_container()
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "BoxLiteWorkerPool: failed to maintain min pool size",
                        exc_info=True,
                    )
                    break
            # Wake dispatch waiters if a container freed up.
            cond = self._worker_available
            if cond is not None:
                async with cond:
                    cond.notify_all()


# ---------------------------------------------------------------------------
# Per-loop facade
# ---------------------------------------------------------------------------


class BoxLiteLoopRunner:
    """Runs agent loops using the BoxLite boxlite container worker pool.

    Implements `LoopRunnerProtocol` for integration with `QueryEngine`.
    One instance per `loop_id`, created by `LoopRunnerFactory` when
    `loop_runner.runner_mode='boxlite'`. Mirrors `ProcessLoopRunner`'s structure —
    only the transport (boxlite exec stream vs mp.Queue) and container lifecycle differ.
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
        self._pool: BoxLiteWorkerPool | None = None

    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Delegate to the shared pool, stream results."""
        pool = await BoxLiteWorkerPool.get_shared_instance(self._config, self._daemon_config)
        self._pool = pool
        async for chunk in pool.submit(request):
            yield chunk

    async def _resolve_pool(self) -> BoxLiteWorkerPool:
        """Return the shared pool, fetching it if `run` hasn't yet bound it."""
        if self._pool is None:
            self._pool = await BoxLiteWorkerPool.get_shared_instance(
                self._config, self._daemon_config
            )
        return self._pool

    async def cancel(self) -> None:
        """Request cooperative cancellation."""
        pool = await self._resolve_pool()
        await pool.cancel_request(self._loop_id)

    async def is_idle(self) -> bool:
        """True when no busy container is mapped to this loop's request."""
        pool = await self._resolve_pool()
        return not pool.is_loop_busy(self._loop_id)

    async def force_kill(self, *, timeout: float = 10.0) -> None:
        """Force-terminate the container mapped to this loop (cancel backstop)."""
        pool = await self._resolve_pool()
        await pool.force_kill_worker_by_loop_id(self._loop_id, timeout=timeout)

    def set_clarification_mode(self, mode: str) -> bool:
        """Hot-swap clarification mode — not yet supported for boxlite mode.

        Container workers don't expose their `SootheRunner` to the main process.
        Returns `False` so the caller falls back to the next-turn path.
        (Future: add a `set_clarification_mode` frame to the exec protocol.)
        """
        return False


__all__ = [
    "BoxLiteLoopRunner",
    "BoxLiteWorkerPool",
]
