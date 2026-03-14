"""Soothe daemon -- background agent runner with Unix socket IPC (RFC-0003).

The daemon wraps ``SootheRunner`` and accepts TUI / headless clients over a
Unix domain socket at ``~/.soothe/soothe.sock``.  Events stream to all
connected clients; only the latest client may send input.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from soothe.config import SOOTHE_HOME, SootheConfig

logger = logging.getLogger(__name__)

_SOCKET_FILENAME = "soothe.sock"
_PID_FILENAME = "soothe.pid"


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
    # Handle None and primitives
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    # Handle lists and tuples
    if isinstance(obj, (list, tuple)):
        return [_serialize_for_json(item) for item in obj]

    # Handle dicts
    if isinstance(obj, dict):
        return {str(k): _serialize_for_json(v) for k, v in obj.items()}

    # Handle Pydantic models (including LangChain messages)
    if hasattr(obj, "model_dump"):
        try:
            dumped = obj.model_dump()
            return _serialize_for_json(dumped)
        except Exception:
            pass

    # Handle objects with dict() method
    if hasattr(obj, "dict"):
        try:
            return _serialize_for_json(obj.dict())
        except Exception:
            pass

    # Handle objects with __dict__
    if hasattr(obj, "__dict__"):
        try:
            return _serialize_for_json(obj.__dict__)
        except Exception:
            pass

    # Fallback to string representation
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
# SootheDaemon
# ---------------------------------------------------------------------------


class SootheDaemon:
    """Background daemon that runs ``SootheRunner`` and serves TUI clients.

    Args:
        config: Soothe configuration.
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        self._config = config or SootheConfig()
        self._clients: list[_ClientConn] = []
        self._server: asyncio.AbstractServer | None = None
        self._runner: Any = None
        self._running = False
        self._thread_stop = threading.Event()
        self._current_input_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Start the daemon server on the Unix socket."""
        from soothe.core.runner import SootheRunner

        sock = socket_path()
        sock.parent.mkdir(parents=True, exist_ok=True)
        if sock.exists():
            sock.unlink()

        self._runner = SootheRunner(self._config)
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(sock),
        )
        self._running = True
        _write_pid()
        logger.info("Soothe daemon listening on %s", sock)

        await self._broadcast({"type": "status", "state": "idle", "thread_id": self._runner.current_thread_id or ""})

    def request_stop(self) -> None:
        """Thread-safe method to request daemon shutdown from any thread."""
        self._thread_stop.set()

    async def serve_forever(self) -> None:
        """Block until the daemon is stopped.

        Supports both signal-based shutdown (main thread) and thread-safe
        shutdown via ``request_stop()`` (background thread).
        """
        if not self._server:
            return

        loop = asyncio.get_running_loop()

        # Signal handlers only work on the main thread; skip when embedded.
        try:
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._thread_stop.set)
        except RuntimeError:
            logger.debug("Cannot set signal handlers (not main thread)")

        input_task = asyncio.create_task(self._input_loop())
        try:
            while not self._thread_stop.is_set():  # noqa: ASYNC110 -- threading.Event, not asyncio.Event
                await asyncio.sleep(0.5)
        finally:
            input_task.cancel()
            await self.stop()

    async def stop(self) -> None:
        """Shut down the daemon gracefully."""
        self._running = False
        await self._broadcast({"type": "status", "state": "stopped"})

        # Clean up runner resources
        if self._runner and hasattr(self._runner, "cleanup"):
            try:
                await self._runner.cleanup()
            except Exception:
                logger.debug("Failed to cleanup runner", exc_info=True)

        for client in self._clients:
            try:
                client.writer.close()
                await client.writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        _cleanup_pid()
        sock = socket_path()
        if sock.exists():
            sock.unlink()
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

        await self._send(
            client,
            {
                "type": "status",
                "state": "idle" if self._running else "stopped",
                "thread_id": self._runner.current_thread_id or "",
            },
        )

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
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
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
                await self._current_input_queue.put({"type": "input", "text": text})
        elif msg_type == "command":
            cmd = msg.get("cmd", "")
            await self._current_input_queue.put({"type": "command", "cmd": cmd})
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
            if msg_type == "command":
                cmd = msg.get("cmd", "")
                if cmd in ("/exit", "/quit"):
                    await self._broadcast({"type": "status", "state": "stopping"})
                    self._running = False
                    break
                await self._broadcast({"type": "event", "data": {"type": "soothe.command", "cmd": cmd}})
            elif msg_type == "input":
                text = msg["text"]
                await self._run_query(text)

    async def _run_query(self, text: str) -> None:
        """Stream a query through SootheRunner and broadcast events."""
        await self._broadcast({"type": "status", "state": "running", "thread_id": self._runner.current_thread_id or ""})

        try:
            async for chunk in self._runner.astream(text, thread_id=self._runner.current_thread_id):
                if not isinstance(chunk, tuple) or len(chunk) != 3:
                    continue
                namespace, mode, data = chunk
                event_msg = {
                    "type": "event",
                    "namespace": list(namespace),
                    "mode": mode,
                    "data": data,
                }
                await self._broadcast(event_msg)
        except Exception as exc:
            logger.error("Daemon query error", exc_info=True)
            await self._broadcast(
                {
                    "type": "event",
                    "namespace": [],
                    "mode": "custom",
                    "data": {"type": "soothe.error", "error": str(exc)},
                }
            )

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
        try:
            client.writer.write(_encode(msg))
            await client.writer.drain()
        except Exception:
            pass

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
    def stop_running() -> bool:
        """Send SIGTERM to the running daemon.

        Returns:
            True if a signal was sent, False if no daemon found.
        """
        pf = pid_path()
        if not pf.exists():
            return False
        try:
            pid = int(pf.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            _cleanup_pid()
            return False


# ---------------------------------------------------------------------------
# DaemonClient -- used by TUI / headless to connect
# ---------------------------------------------------------------------------


class DaemonClient:
    """Async client for connecting to a running SootheDaemon.

    Args:
        sock: Path to the Unix socket.
    """

    def __init__(self, sock: Path | None = None) -> None:
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
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def send_input(self, text: str) -> None:
        """Send user input to the daemon."""
        await self._send({"type": "input", "text": text})

    async def send_command(self, cmd: str) -> None:
        """Send a slash command to the daemon."""
        await self._send({"type": "command", "cmd": cmd})

    async def send_detach(self) -> None:
        """Notify the daemon that this client is detaching."""
        await self._send({"type": "detach"})

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
# PID helpers
# ---------------------------------------------------------------------------


def _write_pid() -> None:
    pf = pid_path()
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(str(os.getpid()))


def _cleanup_pid() -> None:
    pf = pid_path()
    if pf.exists():
        try:
            pf.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Entry point for ``soothe server start``
# ---------------------------------------------------------------------------


def run_daemon(config: SootheConfig | None = None) -> None:
    """Start the daemon in the current process (blocking)."""
    daemon = SootheDaemon(config)

    async def _main() -> None:
        await daemon.start()
        await daemon.serve_forever()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Soothe daemon")
    parser.add_argument("--config", type=str, default=None, help="Config file path")
    args = parser.parse_args()

    cfg: SootheConfig | None = None
    if args.config:
        cfg = SootheConfig.from_yaml_file(args.config)
    else:
        # Try to load from default config location
        from pathlib import Path

        default_config = Path(SOOTHE_HOME) / "config" / "config.yml"
        if default_config.exists():
            cfg = SootheConfig.from_yaml_file(str(default_config))
    run_daemon(cfg)
