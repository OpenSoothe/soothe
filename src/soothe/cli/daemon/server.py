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

from soothe.cli.daemon.paths import pid_path, socket_path
from soothe.cli.daemon.protocol import decode, encode
from soothe.cli.daemon.singleton import (
    acquire_pid_lock,
    cleanup_pid,
    cleanup_socket,
    release_pid_lock,
)
from soothe.cli.thread_logger import InputHistory, ThreadLogger
from soothe.config import SOOTHE_HOME, SootheConfig

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LENGTH = 3
_MSG_PAIR_LENGTH = 2
_CLEANUP_TIMEOUT_S = 3.0
_STOP_TIMEOUT_S = 8.0


@dataclass
class _ClientConn:
    """Internal client connection state."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    can_input: bool = True


class SootheDaemon:
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

    # -- client handling ----------------------------------------------------

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        client = _ClientConn(reader=reader, writer=writer)
        self._clients.append(client)
        logger.info("Client connected (total=%d)", len(self._clients))

        try:
            initial_state = "running" if self._query_running else ("idle" if self._running else "stopped")
            initial_msg = {
                "type": "status",
                "state": initial_state,
                "thread_id": self._runner.current_thread_id or "",
                "input_history": self._input_history.history[-100:],  # Last 100 entries
            }

            client.writer.write(encode(initial_msg))
            await client.writer.drain()
        except Exception:
            logger.exception("Failed to send initial status to client")

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                msg = decode(line)
                if msg is None:
                    continue
                await self._handle_client_message(client, msg)
        except (asyncio.CancelledError, ConnectionError):
            pass
        finally:
            self._clients = [c for c in self._clients if c is not client]
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()
            logger.info("Client disconnected (total=%d)", len(self._clients))

    async def _handle_client_message(
        self,
        client: _ClientConn,
        msg: dict[str, Any],
    ) -> None:
        msg_type = msg.get("type", "")
        if msg_type == "input":
            text = msg.get("text", "").strip()
            if text:
                max_iterations = msg.get("max_iterations")
                parsed_max: int | None = (
                    max_iterations if isinstance(max_iterations, int) and max_iterations > 0 else None
                )
                await self._current_input_queue.put(
                    {
                        "type": "input",
                        "text": text,
                        "autonomous": bool(msg.get("autonomous", False)),
                        "max_iterations": parsed_max,
                    }
                )
        elif msg_type == "command":
            cmd = msg.get("cmd", "")
            await self._current_input_queue.put({"type": "command", "cmd": cmd})
        elif msg_type == "resume_thread":
            thread_id = msg.get("thread_id", "")
            if thread_id:
                self._runner.set_current_thread_id(thread_id)
                await self._broadcast(
                    {"type": "status", "state": "idle", "thread_id": self._runner.current_thread_id or ""}
                )
        elif msg_type == "detach":
            await self._send(client, {"type": "status", "state": "detached"})
        else:
            logger.debug("Unknown client message type: %s", msg_type)

    # -- input processing loop ----------------------------------------------

    async def _input_loop(self) -> None:
        """Process user input from clients in an infinite loop."""
        while self._running:
            try:
                msg = await self._current_input_queue.get()
            except asyncio.CancelledError:
                break

            msg_type = msg.get("type", "")
            try:
                if msg_type == "command":
                    cmd = msg.get("cmd", "")
                    if cmd in ("/exit", "/quit"):
                        await self._broadcast({"type": "status", "state": "stopping"})
                        self._running = False
                        if self._stop_event:
                            self._stop_event.set()
                        break
                    await self._handle_command(cmd)
                elif msg_type == "input":
                    text = msg["text"]
                    await self._run_query(
                        text,
                        autonomous=bool(msg.get("autonomous", False)),
                        max_iterations=msg.get("max_iterations"),
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Daemon input loop handler error")
                self._query_running = False
                await self._broadcast(
                    {
                        "type": "event",
                        "namespace": [],
                        "mode": "custom",
                        "data": {"type": "soothe.error", "error": "Daemon failed to process input"},
                    }
                )
                await self._broadcast(
                    {"type": "status", "state": "idle", "thread_id": self._runner.current_thread_id or ""}
                )

    async def _handle_command(self, cmd: str) -> None:
        """Execute a slash command and broadcast the response.

        Args:
            cmd: The slash command to execute.
        """
        from io import StringIO

        from rich.console import Console

        from soothe.cli.slash_commands import handle_slash_command

        output = StringIO()
        console = Console(file=output, force_terminal=False, width=100)

        should_exit = await handle_slash_command(
            cmd,
            self._runner,
            console,
            current_plan=None,
            thread_logger=self._thread_logger,
            input_history=self._input_history,
        )

        response_text = output.getvalue()
        if response_text.strip():
            await self._broadcast(
                {
                    "type": "command_response",
                    "content": response_text,
                }
            )

        if should_exit:
            await self._broadcast({"type": "status", "state": "stopping"})
            self._running = False
            if self._stop_event:
                self._stop_event.set()

    async def _run_query(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
    ) -> None:
        """Stream a query through SootheRunner and broadcast events."""
        thread_id = self._runner.current_thread_id or ""

        if not self._thread_logger or self._thread_logger._thread_id != thread_id:
            self._thread_logger = ThreadLogger(
                thread_id=thread_id,
                retention_days=self._config.logging.thread_logging.retention_days,
                max_size_mb=self._config.logging.thread_logging.max_size_mb,
            )

        if self._thread_logger:
            self._thread_logger.log_user_input(text)

        # Persist to input history
        if self._input_history:
            self._input_history.add(text)

        self._query_running = True
        await self._broadcast({"type": "status", "state": "running", "thread_id": thread_id})

        full_response: list[str] = []

        try:
            stream_kwargs: dict[str, Any] = {"thread_id": thread_id}
            if autonomous:
                stream_kwargs["autonomous"] = True
                if max_iterations is not None:
                    stream_kwargs["max_iterations"] = max_iterations
            async for chunk in self._runner.astream(text, **stream_kwargs):
                if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LENGTH:
                    continue
                namespace, mode, data = chunk

                self._thread_logger.log(tuple(namespace), mode, data)

                is_msg_pair = isinstance(data, (tuple, list)) and len(data) == _MSG_PAIR_LENGTH
                if not namespace and mode == "messages" and is_msg_pair:
                    msg, _metadata = data
                    from soothe.cli.tui_shared import extract_text_from_ai_message

                    full_response.extend(extract_text_from_ai_message(msg))

                event_msg = {
                    "type": "event",
                    "namespace": list(namespace),
                    "mode": mode,
                    "data": data,
                }
                await self._broadcast(event_msg)
        except asyncio.CancelledError:
            logger.info("Query cancelled during shutdown")
            raise
        except Exception as exc:
            logger.exception("Daemon query error")
            from soothe.utils.error_format import emit_error_event

            await self._broadcast(
                {
                    "type": "event",
                    "namespace": [],
                    "mode": "custom",
                    "data": emit_error_event(exc),
                }
            )
        finally:
            self._query_running = False

        # Re-initialize thread logger if the runner assigned a new thread_id
        # during execution (e.g., _pre_stream created a fresh UUID).
        final_thread_id = self._runner.current_thread_id or ""
        if final_thread_id and final_thread_id != thread_id:
            self._thread_logger = ThreadLogger(
                thread_id=final_thread_id,
                retention_days=self._config.logging.thread_logging.retention_days,
                max_size_mb=self._config.logging.thread_logging.max_size_mb,
            )
            self._thread_logger.log_user_input(text)

        if full_response:
            self._thread_logger.log_assistant_response("".join(full_response))

        await self._broadcast({"type": "status", "state": "idle", "thread_id": final_thread_id})

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
