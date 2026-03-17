"""Soothe daemon -- background agent runner with Unix socket IPC (RFC-0003).

The daemon wraps ``SootheRunner`` and accepts TUI / headless clients over a
Unix domain socket at ``~/.soothe/soothe.sock``.  Events stream to all
connected clients; only the latest client may send input.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import signal
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from soothe.cli.thread_logger import ThreadLogger
from soothe.cli.tui_shared import extract_text_from_ai_message
from soothe.config import SOOTHE_HOME, SootheConfig

logger = logging.getLogger(__name__)

_SOCKET_FILENAME = "soothe.sock"
_PID_FILENAME = "soothe.pid"
_STREAM_CHUNK_LENGTH = 3
_MSG_PAIR_LENGTH = 2
_CLEANUP_TIMEOUT_S = 3.0
_STOP_TIMEOUT_S = 8.0


def _soothe_dir() -> Path:
    return Path(SOOTHE_HOME).expanduser()


def socket_path() -> Path:
    """Return the canonical Unix socket path."""
    return _soothe_dir() / _SOCKET_FILENAME


def pid_path() -> Path:
    """Return the canonical PID file path."""
    return _soothe_dir() / _PID_FILENAME


# ---------------------------------------------------------------------------
# Protocol messages
# ---------------------------------------------------------------------------


def _serialize_for_json(obj: Any) -> Any:
    """Serialize objects for JSON, handling LangChain messages specially."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, (list, tuple)):
        return [_serialize_for_json(item) for item in obj]

    if isinstance(obj, dict):
        return {str(k): _serialize_for_json(v) for k, v in obj.items()}

    if hasattr(obj, "model_dump"):
        with contextlib.suppress(Exception):
            dumped = obj.model_dump()
            return _serialize_for_json(dumped)

    if hasattr(obj, "dict"):
        with contextlib.suppress(Exception):
            return _serialize_for_json(obj.dict())

    if hasattr(obj, "__dict__"):
        with contextlib.suppress(Exception):
            return _serialize_for_json(obj.__dict__)

    return str(obj)


def _encode(msg: dict[str, Any]) -> bytes:
    serialized = _serialize_for_json(msg)
    return (json.dumps(serialized) + "\n").encode()


def _decode(line: bytes) -> dict[str, Any] | None:
    text = line.decode().strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.debug("Invalid daemon protocol line: %s", text[:120])
        return None


# ---------------------------------------------------------------------------
# Client connection
# ---------------------------------------------------------------------------


@dataclass
class _ClientConn:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    can_input: bool = True


# ---------------------------------------------------------------------------
# PID / singleton helpers
# ---------------------------------------------------------------------------


def _write_pid() -> None:
    pf = pid_path()
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(str(os.getpid()))


def _cleanup_pid() -> None:
    pf = pid_path()
    if pf.exists():
        with contextlib.suppress(OSError):
            pf.unlink()


def _cleanup_socket() -> None:
    sock = socket_path()
    if sock.exists():
        with contextlib.suppress(OSError):
            sock.unlink()


def _acquire_pid_lock() -> int | None:
    """Try to acquire an exclusive lock on the PID file.

    Returns:
        File descriptor on success, None if another daemon holds the lock.
    """
    pf = pid_path()
    pf.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(pf), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pid_bytes = str(os.getpid()).encode()
        os.write(fd, pid_bytes)
        os.ftruncate(fd, len(pid_bytes))
        os.fsync(fd)
    except OSError:
        return None
    else:
        return fd


def _release_pid_lock(fd: int) -> None:
    """Release the PID file lock and clean up."""
    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    _cleanup_pid()


# ---------------------------------------------------------------------------
# SootheDaemon
# ---------------------------------------------------------------------------


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
        self._pid_lock_fd: int | None = None

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Start the daemon server on the Unix socket."""
        from soothe.core.runner import SootheRunner

        # Acquire singleton lock *before* heavy init
        self._pid_lock_fd = _acquire_pid_lock()
        if self._pid_lock_fd is None:
            raise RuntimeError("Another Soothe daemon is already running (PID lock held)")

        sock = socket_path()
        sock.parent.mkdir(parents=True, exist_ok=True)

        # Only unlink socket if no live daemon owns it
        if sock.exists() and not self._is_socket_live(sock):
            sock.unlink()
        elif sock.exists():
            _release_pid_lock(self._pid_lock_fd)
            self._pid_lock_fd = None
            raise RuntimeError("Another daemon still owns the socket")

        # Run heavy SootheRunner init off the event loop
        self._runner = await asyncio.to_thread(SootheRunner, self._config)

        self._stop_event = asyncio.Event()
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(sock),
        )
        self._running = True
        logger.info("Soothe daemon listening on %s", sock)

        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

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
            _release_pid_lock(self._pid_lock_fd)
            self._pid_lock_fd = None
        else:
            _cleanup_pid()
        _cleanup_socket()
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
            client.writer.write(
                _encode(
                    {
                        "type": "status",
                        "state": initial_state,
                        "thread_id": self._runner.current_thread_id or "",
                    }
                )
            )
            await client.writer.drain()
        except Exception:
            logger.exception("Failed to send initial status to client")

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                msg = _decode(line)
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

        from soothe.cli.commands import handle_slash_command

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=100)

        should_exit = await handle_slash_command(
            cmd,
            self._runner,
            console,
            current_plan=None,
            thread_logger=self._thread_logger,
            input_history=None,
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
                thread_dir=self._config.logging.thread_logging.dir,
                thread_id=thread_id,
                retention_days=self._config.logging.thread_logging.retention_days,
                max_size_mb=self._config.logging.thread_logging.max_size_mb,
            )

        if self._thread_logger:
            self._thread_logger.log_user_input(text)

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
            await self._broadcast(
                {
                    "type": "event",
                    "namespace": [],
                    "mode": "custom",
                    "data": {"type": "soothe.error", "error": str(exc)},
                }
            )
        finally:
            self._query_running = False

        if full_response:
            self._thread_logger.log_assistant_response("".join(full_response))

        await self._broadcast({"type": "status", "state": "idle", "thread_id": self._runner.current_thread_id or ""})

    # -- broadcast ----------------------------------------------------------

    async def _broadcast(self, msg: dict[str, Any]) -> None:
        data = _encode(msg)
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
            client.writer.write(_encode(msg))
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
            _cleanup_pid()
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
            _cleanup_pid()
            _cleanup_socket()
            return False

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                os.kill(pid, 0)
                time.sleep(0.2)
            except ProcessLookupError:
                _cleanup_pid()
                _cleanup_socket()
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

        _cleanup_pid()
        _cleanup_socket()
        return True


# ---------------------------------------------------------------------------
# DaemonClient -- used by TUI / headless to connect
# ---------------------------------------------------------------------------


class DaemonClient:
    """Async client for connecting to a running SootheDaemon.

    Args:
        sock: Path to the Unix socket.
    """

    def __init__(self, sock: Path | None = None) -> None:
        """Initialize the daemon client.

        Args:
            sock: Path to the Unix socket.
        """
        self._sock = sock or socket_path()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        """Open a connection to the daemon."""
        self._reader, self._writer = await asyncio.open_unix_connection(str(self._sock))

    async def close(self) -> None:
        """Close the connection."""
        if self._writer:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
            self._writer = None
            self._reader = None

    async def send_input(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
    ) -> None:
        """Send user input to the daemon."""
        payload: dict[str, Any] = {"type": "input", "text": text}
        if autonomous:
            payload["autonomous"] = True
            if max_iterations is not None:
                payload["max_iterations"] = max_iterations
        await self._send(payload)

    async def send_command(self, cmd: str) -> None:
        """Send a slash command to the daemon."""
        await self._send({"type": "command", "cmd": cmd})

    async def send_detach(self) -> None:
        """Notify the daemon that this client is detaching."""
        await self._send({"type": "detach"})

    async def send_resume_thread(self, thread_id: str) -> None:
        """Request the daemon to resume a specific thread.

        Args:
            thread_id: The thread ID to resume.
        """
        await self._send({"type": "resume_thread", "thread_id": thread_id})

    async def read_event(self) -> dict[str, Any] | None:
        """Read the next event from the daemon.

        Returns:
            Parsed event dict, or ``None`` on EOF.
        """
        if not self._reader:
            return None
        try:
            line = await self._reader.readline()
            if not line:
                return None
            return _decode(line)
        except (asyncio.CancelledError, ConnectionError):
            return None

    async def _send(self, msg: dict[str, Any]) -> None:
        if not self._writer:
            return
        self._writer.write(_encode(msg))
        await self._writer.drain()


# ---------------------------------------------------------------------------
# Entry point for ``soothe server start``
# ---------------------------------------------------------------------------


def run_daemon(config: SootheConfig | None = None) -> None:
    """Start the daemon in the current process (blocking)."""
    daemon = SootheDaemon(config)

    async def _main() -> None:
        await daemon.start()
        await daemon.serve_forever()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())


if __name__ == "__main__":
    import argparse

    from soothe.cli.main import setup_logging

    parser = argparse.ArgumentParser(description="Soothe daemon")
    parser.add_argument("--config", type=str, default=None, help="Config file path")
    args = parser.parse_args()

    cfg: SootheConfig | None = None
    if args.config:
        cfg = SootheConfig.from_yaml_file(args.config)
    else:
        from pathlib import Path

        default_config = Path(SOOTHE_HOME) / "config" / "config.yml"
        if default_config.exists():
            cfg = SootheConfig.from_yaml_file(str(default_config))

    setup_logging(cfg)
    run_daemon(cfg)
