"""Soothe daemon server - background agent runner with Unix socket IPC."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from soothe.cli.daemon._handlers import DaemonHandlersMixin
from soothe.cli.daemon.paths import pid_path, socket_path
from soothe.cli.daemon.protocol import encode
from soothe.cli.daemon.singleton import (
    acquire_pid_lock,
    cleanup_pid,
    cleanup_socket,
    release_pid_lock,
)
from soothe.cli.thread_logger import InputHistory, ThreadLogger
from soothe.config import SOOTHE_HOME, SootheConfig

logger = logging.getLogger(__name__)

_CLEANUP_TIMEOUT_S = 3.0
_STOP_TIMEOUT_S = 8.0


@dataclass
class _ClientConn:
    """Internal client connection state."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    can_input: bool = True


class SootheDaemon(DaemonHandlersMixin):
    """Background daemon that runs ``SootheRunner`` and serves TUI clients.

    Args:
        config: Soothe configuration.
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        """Initialize the Soothe daemon.

        Args:
            config: Soothe configuration.
        """
        self._config = config or SootheConfig()
        self._clients: list[_ClientConn] = []
        self._server: asyncio.AbstractServer | None = None
        self._runner: Any = None
        self._running = False
        self._query_running = False
        self._thread_stop = threading.Event()
        self._stop_event: asyncio.Event | None = None
        self._current_input_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._cleanup_task: asyncio.Task[None] | None = None
        self._thread_logger: ThreadLogger | None = None
        self._input_history: InputHistory | None = None
        self._pid_lock_fd: int | None = None

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Start the daemon server on the Unix socket."""
        from soothe.core.runner import SootheRunner

        # Acquire singleton lock *before* heavy init
        self._pid_lock_fd = acquire_pid_lock()
        if self._pid_lock_fd is None:
            raise RuntimeError("Another Soothe daemon is already running (PID lock held)")

        sock = socket_path()
        sock.parent.mkdir(parents=True, exist_ok=True)

        # Only unlink socket if no live daemon owns it
        if sock.exists() and not self._is_socket_live(sock):
            sock.unlink()
        elif sock.exists():
            release_pid_lock(self._pid_lock_fd)
            self._pid_lock_fd = None
            raise RuntimeError("Another daemon still owns the socket")

        # Run heavy SootheRunner init off the event loop
        self._runner = await asyncio.to_thread(SootheRunner, self._config)

        # Initialize persistent input history
        self._input_history = InputHistory(history_file=str(Path(SOOTHE_HOME) / "history.json"), max_size=1000)
        logger.info("Input history initialized with %d entries", len(self._input_history.history))

        self._stop_event = asyncio.Event()
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(sock),
            limit=10 * 1024 * 1024,  # 10MB limit for large events
        )
        self._running = True
        logger.info("Soothe daemon listening on %s", sock)

        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

        # Detect incomplete threads from previous daemon run (RFC-0010)
        await self._detect_incomplete_threads()

        await self._broadcast({"type": "status", "state": "idle", "thread_id": self._runner.current_thread_id or ""})

    @staticmethod
    def _is_socket_live(sock: Path) -> bool:
        """Check if a Unix socket is accepting connections."""
        import socket as sock_mod

        try:
            s = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect(str(sock))
            s.close()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            return False
        else:
            return True

    def request_stop(self) -> None:
        """Thread-safe method to request daemon shutdown from any thread."""
        self._thread_stop.set()
        if self._stop_event is not None:
            loop = self._stop_event._loop  # type: ignore[attr-defined]
            loop.call_soon_threadsafe(self._stop_event.set)

    async def _detect_incomplete_threads(self) -> None:
        """Detect threads left in_progress from a previous daemon run (RFC-0010)."""
        runs_dir = Path(SOOTHE_HOME).expanduser() / "runs"  # noqa: ASYNC240
        if not runs_dir.exists():
            return
        try:
            incomplete = []
            for checkpoint_file in runs_dir.glob("*/checkpoint.json"):
                try:
                    data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and data.get("status") == "in_progress":
                        incomplete.append(
                            {
                                "thread_id": checkpoint_file.parent.name,
                                "query": data.get("last_query", "")[:60],
                                "mode": data.get("mode", ""),
                                "completed_steps": len(data.get("completed_step_ids", [])),
                                "goals": len(data.get("goals", [])),
                            }
                        )
                except Exception:  # noqa: S112
                    continue
            if incomplete:
                logger.info(
                    "Found %d incomplete threads from previous run",
                    len(incomplete),
                )
                for t in incomplete:
                    logger.info(
                        "  Thread %s: %s (%d steps done)",
                        t["thread_id"],
                        t["query"],
                        t["completed_steps"],
                    )
            else:
                logger.debug("No incomplete threads found from previous runs")
        except Exception:
            logger.debug("Incomplete thread detection failed", exc_info=True)

    async def serve_forever(self) -> None:
        """Block until the daemon is stopped.

        Supports both signal-based shutdown (main thread) and thread-safe
        shutdown via ``request_stop()`` (background thread).
        """
        if not self._server:
            return

        loop = asyncio.get_running_loop()

        try:
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self.request_stop)
        except RuntimeError:
            logger.debug("Cannot set signal handlers (not main thread)")

        input_task = asyncio.create_task(self._input_loop())
        try:
            await self._stop_event.wait()
        finally:
            input_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await input_task
            await self.stop()

    async def _periodic_cleanup(self) -> None:
        """Run cleanup every 24 hours."""
        while self._running:
            await asyncio.sleep(24 * 3600)
            if self._thread_logger:
                try:
                    deleted = self._thread_logger.cleanup_old_threads()
                    if deleted > 0:
                        logger.info("Cleaned up %d old thread logs", deleted)
                except Exception:
                    logger.warning("Periodic cleanup failed", exc_info=True)

    async def stop(self) -> None:
        """Shut down the daemon gracefully."""
        self._running = False
        self._query_running = False
        with contextlib.suppress(Exception):
            await self._broadcast({"type": "status", "state": "stopped"})

        # Clean up runner resources with a timeout
        if self._runner and hasattr(self._runner, "cleanup"):
            try:
                await asyncio.wait_for(self._runner.cleanup(), timeout=_CLEANUP_TIMEOUT_S)
            except TimeoutError:
                logger.warning("Runner cleanup timed out after %.1fs", _CLEANUP_TIMEOUT_S)
            except Exception:
                logger.debug("Failed to cleanup runner", exc_info=True)

        for client in self._clients:
            with contextlib.suppress(Exception):
                client.writer.close()
                await client.writer.wait_closed()
        self._clients.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Release singleton lock and clean up files
        if self._pid_lock_fd is not None:
            release_pid_lock(self._pid_lock_fd)
            self._pid_lock_fd = None
        else:
            cleanup_pid()
        cleanup_socket()
        logger.info("Soothe daemon stopped")

    # -- broadcast ----------------------------------------------------------

    async def _broadcast(self, msg: dict[str, Any]) -> None:
        data = encode(msg)
        dead: list[_ClientConn] = []
        for client in self._clients:
            try:
                client.writer.write(data)
                await client.writer.drain()
            except Exception:
                dead.append(client)
        for d in dead:
            self._clients = [c for c in self._clients if c is not d]

    async def _send(self, client: _ClientConn, msg: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            client.writer.write(encode(msg))
            await client.writer.drain()

    # -- static helpers -----------------------------------------------------

    @staticmethod
    def is_running() -> bool:
        """Check if a daemon is already running."""
        pf = pid_path()
        if not pf.exists():
            return False
        try:
            pid = int(pf.read_text().strip())
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, PermissionError):
            cleanup_pid()
            return False
        return True

    @staticmethod
    def stop_running(timeout: float = _STOP_TIMEOUT_S) -> bool:
        """Send SIGTERM to the running daemon and wait for it to stop.

        Escalates to SIGKILL if the daemon does not exit within *timeout*
        seconds.

        Args:
            timeout: Maximum seconds to wait before SIGKILL escalation.

        Returns:
            True if a signal was sent and daemon stopped, False if no daemon found.
        """
        import time

        pf = pid_path()
        if not pf.exists():
            return False
        try:
            pid = int(pf.read_text().strip())
            os.kill(pid, signal.SIGTERM)
        except (ValueError, ProcessLookupError, PermissionError):
            cleanup_pid()
            cleanup_socket()
            return False

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                os.kill(pid, 0)
                time.sleep(0.2)
            except ProcessLookupError:
                cleanup_pid()
                cleanup_socket()
                return True
            except PermissionError:
                time.sleep(0.2)

        # SIGKILL escalation
        logger.warning("Daemon did not stop within %.1f seconds, sending SIGKILL", timeout)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)

        # Brief wait for SIGKILL to take effect
        for _ in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                break

        cleanup_pid()
        cleanup_socket()
        return True
