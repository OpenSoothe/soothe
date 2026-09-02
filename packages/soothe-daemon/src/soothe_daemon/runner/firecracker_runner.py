"""Firecracker microVM-based loop runner — one warm microVM per worker slot.

A fourth `LoopRunnerProtocol` substrate (RFC-221) selected by
`LoopRunnerFactory` when `loop_runner.runner_mode='firecracker'`. Each microVM runs the
same `_pool_worker_body` / `SootheRunner` code as the process pool, but
bridges stream chunks host↔guest over **virtio-vsock** instead of
`multiprocessing.Queue`.

**Linux-only — officially supported on Linux only.** Firecracker requires
`AF_VSOCK`, the `firecracker` binary, and a Linux host with KVM. This module
is import-safe on non-Linux (guards `AF_VSOCK` availability so import never
crashes), but `LoopRunnerFactory` raises `RuntimeError` if `runner_mode` is
set to `firecracker` on a non-Linux host. The factory imports this module
lazily inside the `firecracker` branch only, so thread/process/ray paths
never pay the import cost or require vsock.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pickle
import shutil
import socket
import struct
import subprocess
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

# vsock constants. `AF_VSOCK` is only defined on Linux; guard so the module
# imports cleanly on macOS/Windows dev hosts.
_AF_VSOCK = getattr(socket, "AF_VSOCK", 40)
_VMADDR_CID_HOST = 2  # host CID; guest connects here

# Frame protocol: 4-byte big-endian length prefix + payload bytes (pickled).
# The payload is the same 3-tuple convention as `response_bridge.WORKER_MSG_*`:
#   (msg_type, request_id, payload)
_FRAME_HEADER = struct.Struct("!I")
_MAX_FRAME_BYTES = 64 * 1024 * 1024  # 64 MiB safety cap

# Terminal message types (mirror pool_runner._TERMINAL_RESPONSE_TYPES).
_TERMINAL_RESPONSE_TYPES = frozenset({"done", "error", "timeout", "cancelled"})


def _vsock_available() -> bool:
    """Return True when `AF_VSOCK` sockets can be created on this host."""
    if not hasattr(socket, "AF_VSOCK"):
        return False
    try:
        s = socket.socket(_AF_VSOCK, socket.SOCK_STREAM)
    except OSError:
        return False
    s.close()
    return True


# ---------------------------------------------------------------------------
# vsock frame protocol helpers
# ---------------------------------------------------------------------------


def _send_frame(sock: socket.socket, msg: tuple[str, str, Any]) -> None:
    """Send one length-prefixed pickled frame over a socket."""
    payload = pickle.dumps(msg)
    if len(payload) > _MAX_FRAME_BYTES:
        raise ValueError(f"Frame payload too large ({len(payload)} bytes > {_MAX_FRAME_BYTES})")
    sock.sendall(_FRAME_HEADER.pack(len(payload)))
    sock.sendall(payload)


def _recv_exactly(sock: socket.socket, n: int) -> bytes | None:
    """Read exactly `n` bytes; return None on clean EOF."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None if not buf else bytes(buf)
        buf.extend(chunk)
    return bytes(buf)


def _recv_frame(sock: socket.socket) -> tuple[str, str, Any] | None:
    """Receive one length-prefixed pickled frame; return None on clean EOF."""
    header = _recv_exactly(sock, _FRAME_HEADER.size)
    if header is None:
        return None
    (length,) = _FRAME_HEADER.unpack(header)
    if length == 0 or length > _MAX_FRAME_BYTES:
        raise ValueError(f"Invalid frame length: {length}")
    payload = _recv_exactly(sock, length)
    if payload is None:
        return None
    return pickle.loads(payload)  # noqa: S301 — trusted internal transport


# ---------------------------------------------------------------------------
# Host-side vsock stream bridge
# ---------------------------------------------------------------------------


class _VsockStreamBridge:
    """Host-side vsock reader that pushes worker frames into an asyncio queue.

    Opens a host-side vsock socket, reads length-prefixed pickled frames
    (the same 3-tuple convention as `response_bridge.WORKER_MSG_*`), and
    pushes them into an `asyncio.Queue` via `loop.run_in_executor` so the
    daemon event loop stays non-blocking.

    Cancel = send a `"cancel"` frame (cooperative); force-kill = close
    socket + kill VM (handled by the pool).
    """

    def __init__(
        self,
        *,
        worker_index: int,
        vsock_port: int,
        response_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._worker_index = worker_index
        self._vsock_port = vsock_port
        self._response_queue = response_queue
        self._loop = loop
        self._listen_sock: socket.socket | None = None
        self._conn: socket.socket | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = False

    def listen(self) -> None:
        """Bind a host-side vsock listener (called before VM boot)."""
        if not _vsock_available():
            raise RuntimeError(
                "vsock requires a Linux host with AF_VSOCK support; "
                "cannot start Firecracker runner on this platform"
            )
        self._listen_sock = socket.socket(_AF_VSOCK, socket.SOCK_STREAM)
        self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bind to host CID, per-VM port.
        self._listen_sock.bind((_VMADDR_CID_HOST, self._vsock_port))
        self._listen_sock.listen(1)
        self._listen_sock.settimeout(0.5)
        logger.debug(
            "VsockStreamBridge: listening on CID=%d port=%d (worker_index=%d)",
            _VMADDR_CID_HOST,
            self._vsock_port,
            self._worker_index,
        )

    async def wait_for_guest_connect(self, timeout: float = 60.0) -> socket.socket | None:
        """Accept the guest's vsock connection (blocking, run in executor)."""
        assert self._listen_sock is not None
        try:
            conn, _ = await asyncio.wait_for(
                self._loop.run_in_executor(None, self._listen_sock.accept),
                timeout=timeout,
            )
        except TimeoutError:
            logger.error(
                "VsockStreamBridge: guest did not connect within %.1fs (worker_index=%d)",
                timeout,
                self._worker_index,
            )
            return None
        # Disable the accept timeout; the connection is blocking-read.
        conn.settimeout(None)
        self._conn = conn
        return conn

    def start_reader(self) -> None:
        """Start the background reader task after the guest connects."""
        self._reader_task = asyncio.create_task(
            self._read_loop(), name=f"fc-bridge-{self._worker_index}"
        )

    async def _read_loop(self) -> None:
        """Drain frames from the guest socket into the asyncio queue."""
        conn = self._conn
        if conn is None:
            return
        try:
            while not self._closed:
                frame = await self._loop.run_in_executor(None, _recv_frame, conn)
                if frame is None:
                    # Guest closed cleanly.
                    break
                msg_type, request_id, payload = frame
                await self._response_queue.put((msg_type, request_id, payload))
        except (OSError, ValueError) as exc:
            if not self._closed:
                logger.warning(
                    "VsockStreamBridge: read error worker_index=%d: %s",
                    self._worker_index,
                    exc,
                )
        except asyncio.CancelledError:
            raise

    def send_cancel(self, request_id: str) -> None:
        """Send a cooperative cancel frame to the guest."""
        conn = self._conn
        if conn is None or self._closed:
            return
        try:
            _send_frame(conn, ("cancel", request_id, None))
        except OSError:
            logger.debug(
                "VsockStreamBridge: cancel send failed worker_index=%d",
                self._worker_index,
            )

    def close(self) -> None:
        """Close the bridge socket and stop the reader."""
        self._closed = True
        conn = self._conn
        self._conn = None
        listen_sock = self._listen_sock
        self._listen_sock = None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if listen_sock is not None:
            try:
                listen_sock.close()
            except OSError:
                pass
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()


# ---------------------------------------------------------------------------
# Worker VM process abstraction
# ---------------------------------------------------------------------------


@dataclass
class FirecrackerWorker:
    """One warm microVM + its vsock bridge state."""

    worker_id: str
    vm_index: int
    guest_cid: int
    vsock_port: int
    process: subprocess.Popen | None = None
    api_socket_path: str = ""
    bridge: _VsockStreamBridge | None = None
    started_at: datetime = field(default_factory=datetime.now)
    last_heartbeat_at: datetime = field(default_factory=datetime.now)
    requests_completed: int = 0
    busy_loop_id: str | None = None
    busy_request_id: str | None = None

    @property
    def is_alive(self) -> bool:
        """True when the VM process is still running."""
        return self.process is not None and self.process.poll() is None

    def mark_busy(self, loop_id: str, request_id: str) -> None:
        """Mark this VM as executing a request."""
        self.busy_loop_id = loop_id
        self.busy_request_id = request_id

    def mark_idle(self) -> None:
        """Return this VM to the idle pool."""
        self.busy_loop_id = None
        self.busy_request_id = None
        self.requests_completed += 1


# ---------------------------------------------------------------------------
# Warm microVM pool (singleton)
# ---------------------------------------------------------------------------


class FirecrackerWorkerPool:
    """Singleton pool of warm Firecracker microVMs for loop execution.

    Mirrors `ProcessPool`'s shape (singleton, pre-warm, submit → async
    generator, cancel_request, force_kill_worker_by_loop_id) so
    `QueryEngine` is fully decoupled per RFC-221.

    Each VM boots the configured kernel + rootfs, runs a guest-side
    entrypoint that imports `_pool_worker_body` and speaks the vsock frame
    protocol. `submit(request)` acquires an idle VM, sends the
    `LoopRunRequest` (pickled, spawn-safe), and returns the bridge's
    async generator.
    """

    _shared_pool: FirecrackerWorkerPool | None = None
    _pool_lock: asyncio.Lock | None = None

    def __init__(
        self,
        config: SootheConfig,
        daemon_config: SootheDaemonConfig,
    ) -> None:
        self._config = config
        fc = daemon_config.loop_runner.firecracker
        self._fc_config = fc
        self._min_pool_size = fc.min_pool_size
        self._max_pool_size = max(fc.min_pool_size, fc.max_pool_size)
        self._idle_timeout_seconds = fc.idle_timeout_seconds
        self._max_requests_per_worker = fc.max_requests_per_worker
        self._request_timeout_seconds = fc.request_timeout_seconds
        self._reuse_runner = fc.reuse_runner
        self._warmup_runner = fc.warmup_runner
        self._warmup_core_agent = fc.warmup_core_agent
        self._vsock_port_base = fc.vsock_port_base
        self._vm_cpu_count = fc.vm_cpu_count
        self._vm_mem_mib = fc.vm_mem_mib
        self._kernel_image_path = fc.kernel_image_path
        self._rootfs_image_path = fc.rootfs_image_path
        self._firecracker_binary_path = fc.firecracker_binary_path
        self._workspace_mount_mode = fc.workspace_mount_mode
        self._extra_kernel_args = fc.extra_kernel_args

        self._workers: dict[str, FirecrackerWorker] = {}
        self._workers_by_loop_id: dict[str, str] = {}
        self._dispatch_semaphore: asyncio.Semaphore | None = None
        self._worker_available: asyncio.Condition | None = None
        self._pending_responses: dict[str, asyncio.Queue] = {}
        self._running = False
        self._next_vm_index: int = 0
        self._next_guest_cid: int = 3  # CID 2 is host; guests start at 3
        self._health_task: asyncio.Task[None] | None = None

    # -- singleton lifecycle ------------------------------------------------

    @classmethod
    async def get_shared_instance(
        cls, config: SootheConfig, daemon_config: SootheDaemonConfig
    ) -> FirecrackerWorkerPool:
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
        """Pre-warm `min_pool_size` microVMs at daemon startup."""
        self._running = True
        self._dispatch_semaphore = asyncio.Semaphore(self._max_pool_size)
        self._worker_available = asyncio.Condition()
        logger.info(
            "FirecrackerWorkerPool: starting (min=%d, max=%d VMs, cpu=%d, mem=%dMiB)",
            self._min_pool_size,
            self._max_pool_size,
            self._vm_cpu_count,
            self._vm_mem_mib,
        )
        for _ in range(self._min_pool_size):
            await self._spawn_warm_vm()
        self._health_task = asyncio.create_task(self._health_loop(), name="fc-health")

    async def _stop(self) -> None:
        """Shutdown all VMs."""
        self._running = False
        if self._health_task is not None:
            self._health_task.cancel()
            try:
                await self._health_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        for worker in list(self._workers.values()):
            await self._shutdown_vm(worker)
        self._workers.clear()
        self._workers_by_loop_id.clear()
        self._pending_responses.clear()
        logger.info("FirecrackerWorkerPool: stopped")

    # -- VM lifecycle -------------------------------------------------------

    async def _spawn_warm_vm(self) -> FirecrackerWorker:
        """Boot one warm microVM and wait for the guest to connect over vsock."""
        worker_id = f"fc-{uuid.uuid4().hex[:8]}"
        vm_index = self._next_vm_index
        self._next_vm_index += 1
        guest_cid = self._next_guest_cid
        self._next_guest_cid += 1
        vsock_port = self._vsock_port_base + vm_index

        loop = asyncio.get_running_loop()

        # Set up the host-side vsock listener BEFORE booting the VM.
        bridge = _VsockStreamBridge(
            worker_index=vm_index,
            vsock_port=vsock_port,
            response_queue=asyncio.Queue(maxsize=100),
            loop=loop,
        )
        bridge.listen()

        # Boot the VM via the firecracker REST API over a UNIX socket.
        api_socket_path = f"/tmp/soothe-fc-{worker_id}.sock"
        vm = await self._boot_vm(
            worker_id=worker_id,
            vm_index=vm_index,
            guest_cid=guest_cid,
            vsock_port=vsock_port,
            api_socket_path=api_socket_path,
        )

        worker = FirecrackerWorker(
            worker_id=worker_id,
            vm_index=vm_index,
            guest_cid=guest_cid,
            vsock_port=vsock_port,
            process=vm,
            api_socket_path=api_socket_path,
            bridge=bridge,
        )
        self._workers[worker_id] = worker

        # Wait for the guest to connect back over vsock.
        conn = await bridge.wait_for_guest_connect(timeout=60.0)
        if conn is None:
            logger.error(
                "FirecrackerWorkerPool: guest did not connect for worker=%s; shutting down VM",
                worker_id,
            )
            await self._shutdown_vm(worker)
            raise RuntimeError(f"Firecracker VM {worker_id} guest connect timeout")
        bridge.start_reader()
        logger.info(
            "FirecrackerWorkerPool: warm VM %s ready (cid=%d, port=%d)",
            worker_id,
            guest_cid,
            vsock_port,
        )
        return worker

    async def _boot_vm(
        self,
        *,
        worker_id: str,
        vm_index: int,
        guest_cid: int,
        vsock_port: int,
        api_socket_path: str,
    ) -> subprocess.Popen:
        """Spawn the firecracker binary and drive its REST API to boot.

        Uses the firecracker REST API over a UNIX socket to configure
        boot-source, machine-config, and vsock, then issue a start.
        """
        binary = self._firecracker_binary_path
        if not (shutil.which(binary) or os.path.isfile(binary)):
            raise FileNotFoundError(
                f"Firecracker binary not found: {binary}. "
                "Install firecracker and set firecracker.firecracker_binary_path."
            )
        if not os.path.isfile(self._kernel_image_path):
            raise FileNotFoundError(
                f"Kernel image not found: {self._kernel_image_path}. "
                "Set firecracker.kernel_image_path."
            )
        if not os.path.isfile(self._rootfs_image_path):
            raise FileNotFoundError(
                f"Rootfs image not found: {self._rootfs_image_path}. "
                "Set firecracker.rootfs_image_path."
            )

        # Spawn firecracker with its API socket.
        proc = subprocess.Popen(
            [binary, "--api-sock", api_socket_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Give the API socket a moment to appear.
        await asyncio.sleep(0.1)

        kernel_args = (
            f"console=ttyS0 reboot=k panic=1 "
            f"soothe_worker_id={worker_id} "
            f"soothe_vsock_port={vsock_port} "
            f"soothe_guest_cid={guest_cid}"
        )
        if self._extra_kernel_args:
            kernel_args += f" {self._extra_kernel_args}"

        boot_source = {
            "kernel_image_path": self._kernel_image_path,
            "boot_args": kernel_args,
        }
        machine_config = {
            "vcpu_count": self._vm_cpu_count,
            "mem_size_mib": self._vm_mem_mib,
        }
        vsock_config = {
            "vsock_id": f"soothe-vsock-{worker_id}",
            "guest_cid": guest_cid,
        }

        # Drive the REST API (PUT requests over the UNIX socket).
        # We use curl here for simplicity; a production implementation may
        # use a Python HTTP client over the UNIX socket.
        await self._firecracker_api_put(api_socket_path, "/boot-source", boot_source)
        await self._firecracker_api_put(api_socket_path, "/machine-config", machine_config)
        await self._firecracker_api_put(api_socket_path, "/vsock", vsock_config)

        # Attach the rootfs as a block device.
        rootfs_drive = {
            "drive_id": f"rootfs-{worker_id}",
            "path_on_host": self._rootfs_image_path,
            "is_root_device": True,
            "is_read_only": False,
        }
        await self._firecracker_api_put(api_socket_path, "/drives/rootfs", rootfs_drive)

        # Issue the start.
        await self._firecracker_api_put(
            api_socket_path, "/actions", {"action_type": "InstanceStart"}
        )
        logger.debug(
            "FirecrackerWorkerPool: booted VM %s (pid=%d, cid=%d)",
            worker_id,
            proc.pid,
            guest_cid,
        )
        return proc

    async def _firecracker_api_put(self, api_socket: str, path: str, body: dict[str, Any]) -> None:
        """Send a PUT to the firecracker REST API over its UNIX socket."""
        import json

        url = f"http://unix{path}"
        payload = json.dumps(body)
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl",
                "-s",
                "--unix-socket",
                api_socket,
                "-X",
                "PUT",
                "-H",
                "Content-Type: application/json",
                "-d",
                payload,
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except FileNotFoundError as exc:
            raise RuntimeError("curl is required to drive the firecracker API socket") from exc

    async def _shutdown_vm(self, worker: FirecrackerWorker) -> None:
        """Gracefully stop a microVM."""
        if worker.bridge is not None:
            worker.bridge.close()
        proc = worker.process
        if proc is not None and proc.poll() is None:
            # Try graceful CtrlAltDel via the API.
            try:
                await self._firecracker_api_put(
                    worker.api_socket_path,
                    "/actions",
                    {"action_type": "CtrlAltDel"},
                )
                loop = asyncio.get_event_loop()
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, proc.wait),
                        timeout=5.0,
                    )
                except TimeoutError:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(
                            loop.run_in_executor(None, proc.wait),
                            timeout=3.0,
                        )
                    except TimeoutError:
                        proc.kill()
            except Exception:  # noqa: BLE001
                # API call failed; fall back to SIGTERM/SIGKILL.
                proc.terminate()
                try:
                    await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, proc.wait),
                        timeout=3.0,
                    )
                except TimeoutError:
                    proc.kill()
        # Clean up the API socket file.
        if worker.api_socket_path and os.path.exists(worker.api_socket_path):
            try:
                os.unlink(worker.api_socket_path)
            except OSError:
                pass

    # -- dispatch -----------------------------------------------------------

    async def submit(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Acquire an idle VM, send the request, stream results.

        Mirrors `ProcessPool.submit`'s structure: acquire a worker under the
        dispatch semaphore, register routing, send the request, then drain
        the response queue yielding chunks until a terminal frame.
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
                raise RuntimeError("Firecracker pool is not started")

            worker: FirecrackerWorker
            while True:
                worker = await self._try_acquire_idle_worker()
                if worker is not None:
                    break
                if not self._running:
                    raise RuntimeError("Firecracker pool is shutting down")
                async with cond:
                    await cond.wait()

            response_queue = asyncio.Queue(maxsize=100)
            self._pending_responses[request_id] = response_queue
            self._workers_by_loop_id[request.loop_id] = worker.worker_id
            worker.mark_busy(request.loop_id, request_id)

            # Send the request over vsock to the guest.
            assert worker.bridge is not None
            conn = worker.bridge._conn
            if conn is None:
                raise RuntimeError(f"VM {worker.worker_id} has no vsock connection")
            spawn_safe = spawn_safe_config(self._config)
            _send_frame(
                conn,
                ("request", request_id, (request, spawn_safe)),
            )

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
                "FirecrackerWorkerPool: request %s cancelled by client disconnect",
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

    async def _try_acquire_idle_worker(self) -> FirecrackerWorker | None:
        """Find an idle, alive VM; spawn a new one if under max and none idle."""
        for worker in self._workers.values():
            if worker.busy_loop_id is None and worker.is_alive:
                return worker
        # Scale up if under max.
        if len(self._workers) < self._max_pool_size:
            try:
                return await self._spawn_warm_vm()
            except Exception:  # noqa: BLE001
                logger.warning("FirecrackerWorkerPool: failed to spawn warm VM", exc_info=True)
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
        """Send a cooperative cancel frame to the VM running this loop."""
        worker_id = self._workers_by_loop_id.get(loop_id)
        if worker_id is None:
            logger.debug("FirecrackerWorkerPool: no active request for loop_id=%s", loop_id)
            return
        worker = self._workers.get(worker_id)
        if worker is None or worker.bridge is None:
            logger.debug(
                "FirecrackerWorkerPool: worker %s not found for loop_id=%s",
                worker_id,
                loop_id,
            )
            return
        if worker.busy_request_id is not None:
            worker.bridge.send_cancel(worker.busy_request_id)
        logger.info(
            "FirecrackerWorkerPool: cancel sent to VM %s for loop=%s",
            worker_id,
            loop_id[:16],
        )

    def is_loop_busy(self, loop_id: str) -> bool:
        """True when a busy VM is mapped to this loop's request."""
        worker_id = self._workers_by_loop_id.get(loop_id)
        if worker_id is None:
            return False
        worker = self._workers.get(worker_id)
        return worker is not None and worker.busy_loop_id == loop_id

    async def force_kill_worker_by_loop_id(self, loop_id: str, *, timeout: float = 10.0) -> None:
        """Force-shutdown the VM mapped to this loop (cancel backstop)."""
        worker_id = self._workers_by_loop_id.pop(loop_id, None)
        if worker_id is None:
            return
        worker = self._workers.get(worker_id)
        if worker is None:
            return
        logger.warning(
            "FirecrackerWorkerPool: force-killing VM %s for loop=%s",
            worker_id,
            loop_id[:16],
        )
        await self._shutdown_vm(worker)
        self._workers.pop(worker_id, None)
        self._pending_responses.pop(worker.busy_request_id or "", None)
        # Respawn a warm VM to maintain pool size.
        if self._running and len(self._workers) < self._min_pool_size:
            try:
                await self._spawn_warm_vm()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "FirecrackerWorkerPool: failed to respawn VM after force-kill",
                    exc_info=True,
                )
        # Wake any dispatch waiters.
        cond = self._worker_available
        if cond is not None:
            async with cond:
                cond.notify_all()

    # -- health / idle reaping ---------------------------------------------

    async def _health_loop(self) -> None:
        """Periodically reap idle/dead VMs and maintain min pool size."""
        while self._running:
            await asyncio.sleep(30.0)
            now = datetime.now()
            for worker_id, worker in list(self._workers.items()):
                if worker.busy_loop_id is not None:
                    continue
                idle_seconds = (now - worker.last_heartbeat_at).total_seconds()
                if idle_seconds > self._idle_timeout_seconds:
                    logger.info(
                        "FirecrackerWorkerPool: idle VM %s timed out (%.0fs); shutting down",
                        worker_id,
                        idle_seconds,
                    )
                    await self._shutdown_vm(worker)
                    self._workers.pop(worker_id, None)
            # Maintain min pool size.
            while self._running and len(self._workers) < self._min_pool_size:
                try:
                    await self._spawn_warm_vm()
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "FirecrackerWorkerPool: failed to maintain min pool size",
                        exc_info=True,
                    )
                    break
            # Wake dispatch waiters if a VM freed up.
            cond = self._worker_available
            if cond is not None:
                async with cond:
                    cond.notify_all()


# ---------------------------------------------------------------------------
# Per-loop facade
# ---------------------------------------------------------------------------


class FirecrackerLoopRunner:
    """Runs agent loops using the Firecracker microVM worker pool.

    Implements `LoopRunnerProtocol` for integration with `QueryEngine`.
    One instance per `loop_id`, created by `LoopRunnerFactory` when
    `loop_runner.runner_mode='firecracker'`. Mirrors `ProcessLoopRunner`'s structure —
    only the transport (vsock vs mp.Queue) and VM lifecycle differ.
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
        self._pool: FirecrackerWorkerPool | None = None

    async def run(self, request: LoopRunRequest) -> AsyncIterator[StreamChunk]:
        """Delegate to the shared pool, stream results."""
        pool = await FirecrackerWorkerPool.get_shared_instance(self._config, self._daemon_config)
        self._pool = pool
        async for chunk in pool.submit(request):
            yield chunk

    async def _resolve_pool(self) -> FirecrackerWorkerPool:
        """Return the shared pool, fetching it if `run` hasn't yet bound it.

        `cancel` / `is_idle` / `force_kill` may be called before `run`
        has bound `self._pool` (e.g. cancel racing dispatch). Resolving the
        shared instance here keeps those paths safe to call pre-dispatch.
        """
        if self._pool is None:
            self._pool = await FirecrackerWorkerPool.get_shared_instance(
                self._config, self._daemon_config
            )
        return self._pool

    async def cancel(self) -> None:
        """Request cooperative cancellation."""
        pool = await self._resolve_pool()
        await pool.cancel_request(self._loop_id)

    async def is_idle(self) -> bool:
        """True when no busy VM is mapped to this loop's request."""
        pool = await self._resolve_pool()
        return not pool.is_loop_busy(self._loop_id)

    async def force_kill(self, *, timeout: float = 10.0) -> None:
        """Force-terminate the VM mapped to this loop (cancel backstop)."""
        pool = await self._resolve_pool()
        await pool.force_kill_worker_by_loop_id(self._loop_id, timeout=timeout)

    def set_clarification_mode(self, mode: str) -> bool:
        """Hot-swap clarification mode — not yet supported for firecracker mode.

        VM workers don't expose their `SootheRunner` to the main process.
        Returns `False` so the caller falls back to the next-turn path.
        (Future: add a `set_clarification_mode` frame to the vsock protocol.)
        """
        return False


__all__ = [
    "FirecrackerLoopRunner",
    "FirecrackerWorkerPool",
]
