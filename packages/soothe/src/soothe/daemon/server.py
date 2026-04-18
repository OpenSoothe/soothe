"""Soothe daemon server - background agent runner with WebSocket IPC."""

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

from soothe_sdk.client.protocol import encode

from soothe.config import SOOTHE_HOME, SootheConfig
from soothe.core import resolve_daemon_workspace
from soothe.daemon._handlers import DaemonHandlersMixin
from soothe.daemon.client_session import ClientSessionManager
from soothe.daemon.event_bus import EventBus
from soothe.daemon.message_router import MessageRouter
from soothe.daemon.paths import pid_path
from soothe.daemon.query_engine import QueryEngine
from soothe.daemon.singleton import (
    acquire_pid_lock,
    cleanup_pid,
    release_pid_lock,
)
from soothe.daemon.thread_state import ThreadStateRegistry
from soothe.daemon.transport_manager import TransportManager
from soothe.logging import ThreadLogger
from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)

_CLEANUP_TIMEOUT_S = 3.0
_STOP_TIMEOUT_S = 8.0
_HEARTBEAT_INTERVAL_S = 5.0  # Broadcast heartbeat every 5 seconds


def _log_startup_banner(transport_manager: TransportManager | None) -> None:
    """Log a clean startup banner with transport info.

    Args:
        transport_manager: The transport manager with started transports.
    """
    from soothe import __version__

    # Get transport details
    transports = transport_manager.get_transport_info() if transport_manager else []
    if transports:
        transport_str = " | ".join(f"{t['type']}: {t['client_count']} clients" for t in transports)
    else:
        transport_str = "none"

    # Compact single-line banner
    logger.info(
        "╭─ Soothe v%s ── transports: %s ──╯",
        __version__,
        transport_str,
    )


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

    def __init__(
        self,
        config: SootheConfig | None = None,
        *,
        handle_sigint_shutdown: bool = True,
    ) -> None:
        """Initialize the Soothe daemon.

        Args:
            config: Soothe configuration.
            handle_sigint_shutdown: Whether SIGINT should trigger daemon shutdown.
                Disable for detached/background mode to avoid accidental Ctrl+C shutdown.
        """
        self._config = config or SootheConfig()
        self._handle_sigint_shutdown = handle_sigint_shutdown

        # Resolve daemon workspace
        self._daemon_workspace = resolve_daemon_workspace(self._config.workspace_dir)
        logger.info("Daemon workspace: %s", self._daemon_workspace)

        # Update config with resolved workspace
        self._config.workspace_dir = str(self._daemon_workspace)
        self._clients: list[_ClientConn] = []
        self._server: asyncio.AbstractServer | None = None
        self._runner: Any = None
        self._running = False
        self._query_running = False  # Deprecated: use _active_threads instead
        self._current_query_task: asyncio.Task | None = None
        self._thread_stop = threading.Event()
        self._stop_event: asyncio.Event | None = None
        self._current_input_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._cleanup_task: asyncio.Task[None] | None = None
        self._inactivity_check_task: asyncio.Task[None] | None = None
        self._input_loop_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._thread_logger: ThreadLogger | None = None
        self._pid_lock_fd: int | None = None
        # Transport manager for multi-transport support (RFC-0013)
        self._transport_manager: TransportManager | None = None
        # Event bus architecture (RFC-0013, IG-047)
        self._event_bus: EventBus = EventBus()
        self._session_manager: ClientSessionManager = ClientSessionManager(
            self._event_bus,
            cancel_callback=self._cancel_thread,  # RFC-0013: auto-cancel on disconnect
        )
        # Multi-threading support (RFC-402)
        self._thread_executor: Any = None  # ThreadExecutor instance
        self._active_threads: dict[str, asyncio.Task] = {}  # thread_id -> Task mapping
        self._pending_interrupt_responses: dict[str, asyncio.Future[dict[str, Any]]] = {}
        # Lock protecting query state transitions (_active_threads, _query_running, _current_query_task)
        self._query_state_lock = asyncio.Lock()
        # Daemon readiness state for explicit startup handshake (RFC-0023)
        self._readiness_state: str = "starting"
        self._readiness_message: str | None = None
        # Per-thread isolation (IG-110): populated when runner exists
        self._thread_registry: ThreadStateRegistry = ThreadStateRegistry()
        # Global cross-thread input history
        self._global_history: Any = None  # GlobalInputHistory | None
        self._query_engine: QueryEngine = QueryEngine(self)
        self._message_router: MessageRouter = MessageRouter(self)

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Start the daemon server using the transport manager."""
        from concurrent.futures import ThreadPoolExecutor

        from soothe.core.runner import SootheRunner

        # Acquire singleton lock *before* heavy init
        self._pid_lock_fd = acquire_pid_lock()
        if self._pid_lock_fd is None:
            raise RuntimeError("Another Soothe daemon is already running (PID lock held)")

        self._readiness_state = "warming"
        self._readiness_message = None

        try:
            # Configure custom default executor for asyncio.to_thread() calls
            # This prevents "couldn't stop thread" errors on daemon shutdown
            loop = asyncio.get_running_loop()
            self._default_executor = ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="daemon-async"
            )
            loop.set_default_executor(self._default_executor)

            # Run heavy SootheRunner init off the event loop
            try:
                self._runner = await asyncio.to_thread(SootheRunner, self._config)
            except Exception as exc:
                self._readiness_state = "error"
                self._readiness_message = str(exc)
                raise

            # QueryEngine is created in __init__; runner is now available for queries
            # Initialize global cross-thread input history
            if self._config.logging.global_history.enabled:
                from soothe.logging.global_history import GlobalInputHistory

                self._global_history = GlobalInputHistory(
                    max_size=self._config.logging.global_history.max_size,
                    dedup_window=self._config.logging.global_history.dedup_window,
                )
                removed = self._global_history.cleanup_old_entries(
                    retention_days=self._config.logging.global_history.retention_days
                )
                if removed > 0:
                    logger.info("Cleaned up %d old global history entries", removed)
                logger.debug(
                    "Global input history initialized at %s", self._global_history.history_file
                )

            self._stop_event = asyncio.Event()
            self._running = True

            # Initialize transport manager (RFC-0013)
            # Create ThreadContextManager for HTTP REST transport (RFC-402)
            from soothe.core.thread import ThreadExecutor

            thread_manager = self._runner.thread_context_manager()

            # Initialize ThreadExecutor for multi-threading support (RFC-402)
            max_concurrent = getattr(self._config.daemon, "max_concurrent_threads", 100)
            self._thread_executor = ThreadExecutor(
                self._runner, max_concurrent_threads=max_concurrent
            )
            logger.debug(
                "ThreadExecutor initialized with max_concurrent_threads=%d", max_concurrent
            )

            self._transport_manager = TransportManager(
                self._config.daemon,
                thread_manager=thread_manager,
                runner=self._runner,
                soothe_config=self._config,
                session_manager=self._session_manager,
            )
            self._transport_manager.set_message_handler(self._handle_transport_message)
            self._transport_manager.set_handshake_callback(self._get_handshake_messages)
            await self._transport_manager.start_all()

            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            self._inactivity_check_task = asyncio.create_task(self._periodic_inactivity_check())
            self._heartbeat_task = asyncio.create_task(self._periodic_heartbeat())

            # Detect incomplete threads from previous daemon run (RFC-0010)
            await self._detect_incomplete_threads()

            await self._broadcast(
                {
                    "type": "status",
                    "state": "idle",
                    "thread_id": self._runner.current_thread_id or "",
                }
            )
            if self._input_loop_task is None or self._input_loop_task.done():
                self._input_loop_task = asyncio.create_task(self._input_loop())

            self._readiness_state = "ready"
            self._readiness_message = None

            # Log startup banner with transport info
            _log_startup_banner(self._transport_manager)
        except Exception as exc:
            # Startup failed - cleanup and release PID lock
            self._readiness_state = "error"
            self._readiness_message = str(exc)
            logger.exception("Daemon startup failed")

            # Stop any partially initialized resources
            if self._transport_manager:
                await self._transport_manager.stop_all()
            if self._runner and hasattr(self._runner, "cleanup"):
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self._runner.cleanup(), timeout=_CLEANUP_TIMEOUT_S)

            # Release PID lock
            if self._pid_lock_fd is not None:
                release_pid_lock(self._pid_lock_fd)
                self._pid_lock_fd = None
            else:
                cleanup_pid()

            raise

    def daemon_ready_message(self) -> dict[str, Any]:
        """Return the current daemon readiness message for client handshakes."""
        return {
            "type": "daemon_ready",
            "state": self._readiness_state,
            "message": self._readiness_message,
        }

    def _get_handshake_messages(self, _transport_client: Any) -> list[dict[str, Any]]:
        """Get initial handshake messages for a new client connection.

        Args:
            _transport_client: Transport-specific client object (unused).

        Returns:
            List of initial messages to send to the client.
        """
        # Check both _active_threads and _query_running for reliable state detection
        has_active_threads = hasattr(self, "_active_threads") and bool(self._active_threads)
        has_active_query = has_active_threads or self._query_running
        initial_state = "running" if has_active_query else ("idle" if self._running else "stopped")
        initial_msg = {
            "type": "status",
            "state": initial_state,
            "thread_id": "",  # Don't leak cached thread ID - client will request new/resume explicitly
            "input_history": [],  # Don't send history on initial connect - only when resuming
        }
        return [initial_msg, self.daemon_ready_message()]

    @staticmethod
    def _is_port_live(host: str, port: int) -> bool:
        """Check if a WebSocket server is accepting connections.

        Uses a simple TCP connection check without sending WebSocket upgrade.
        This avoids corrupting the WebSocket server state.

        Args:
            host: Host address to check.
            port: TCP port number.

        Returns:
            True if server is accepting TCP connections, False otherwise.
        """
        import socket as sock_mod

        try:
            s = sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((host, port))
            # Just close immediately - we only need to verify the port is open
            # Sending a WebSocket upgrade request without proper close corrupts server state
            s.close()
        except (ConnectionRefusedError, OSError, TimeoutError):
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
        """Detect threads left in_progress from a previous daemon run (RFC-0010, IG-138).

        If auto_cancel_on_startup is enabled, threads older than thread_max_age_hours
        are automatically cancelled.
        """
        from datetime import datetime, timedelta

        runs_dir = Path(SOOTHE_HOME).expanduser() / "runs"  # noqa: ASYNC240
        if not runs_dir.exists():
            return
        try:
            incomplete = []
            auto_cancel = self._config.daemon.auto_cancel_on_startup
            max_age_hours = self._config.daemon.thread_max_age_hours
            max_age_threshold = (
                datetime.now(tz=None) - timedelta(hours=max_age_hours) if auto_cancel else None
            )

            for checkpoint_file in runs_dir.glob("*/checkpoint.json"):
                try:
                    data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and data.get("status") == "in_progress":
                        thread_info = {
                            "thread_id": checkpoint_file.parent.name,
                            "query": preview_first(data.get("last_query", ""), 60),
                            "mode": data.get("mode", ""),
                            "completed_steps": len(data.get("completed_step_ids", [])),
                            "goals": len(data.get("goals", [])),
                            "updated_at": data.get("updated_at"),
                        }
                        incomplete.append(thread_info)

                        # Auto-cancel very old threads (IG-138)
                        if auto_cancel and max_age_threshold and thread_info["updated_at"]:
                            try:
                                # Parse timestamp (may be ISO string or other format)
                                updated_str = thread_info["updated_at"]
                                if isinstance(updated_str, str):
                                    # Try parsing ISO format (handle both "Z" suffix and standard ISO)
                                    import re

                                    normalized = re.sub(r"Z$", "+00:00", updated_str)
                                    try:
                                        updated_at = datetime.fromisoformat(normalized)
                                    except ValueError:
                                        logger.debug(
                                            "Failed to parse timestamp: %s for thread %s",
                                            updated_str,
                                            thread_info["thread_id"],
                                        )
                                        continue

                                    if updated_at.tzinfo is not None:
                                        updated_at = updated_at.replace(tzinfo=None)
                                else:
                                    # Skip if not a string
                                    continue

                                if updated_at < max_age_threshold:
                                    thread_id = thread_info["thread_id"]
                                    age_hours = (
                                        datetime.now(tz=None) - updated_at
                                    ).total_seconds() / 3600

                                    logger.warning(
                                        "Auto-cancelling very old thread %s (age: %.1f hours > max: %d)",
                                        thread_id,
                                        age_hours,
                                        max_age_hours,
                                    )

                                    # Cancel the thread using ThreadContextManager
                                    if self._runner:
                                        try:
                                            thread_manager = self._runner.thread_context_manager()
                                            await thread_manager.cancel_thread(thread_id)
                                            logger.info(
                                                "Successfully auto-cancelled thread %s", thread_id
                                            )
                                        except Exception:
                                            logger.warning(
                                                "Failed to cancel thread %s",
                                                thread_id,
                                                exc_info=True,
                                            )
                            except (ValueError, TypeError):
                                # Skip if timestamp parsing fails
                                logger.debug(
                                    "Failed to parse timestamp for thread %s",
                                    thread_info["thread_id"],
                                )
                                continue
                except Exception:  # noqa: S112
                    continue

            if incomplete:
                # Filter out auto-cancelled threads for reporting
                remaining = [
                    t
                    for t in incomplete
                    if t["thread_id"] not in getattr(self, "_cancelled_threads", set())
                ]
                if remaining:
                    logger.info(
                        "Found %d incomplete threads from previous run (%d auto-cancelled)",
                        len(remaining),
                        len(incomplete) - len(remaining),
                    )
                    for t in remaining:
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
        # With multi-transport architecture, we don't need self._server
        # The transport manager handles all servers
        if not self._transport_manager and not self._server:
            return

        loop = asyncio.get_running_loop()

        try:
            signals = [signal.SIGTERM]
            if self._handle_sigint_shutdown:
                signals.append(signal.SIGINT)
            for sig in signals:
                loop.add_signal_handler(sig, self.request_stop)
        except RuntimeError:
            logger.debug("Cannot set signal handlers (not main thread)")

        if self._input_loop_task is None or self._input_loop_task.done():
            self._input_loop_task = asyncio.create_task(self._input_loop())
        try:
            await self._stop_event.wait()
        finally:
            if self._input_loop_task is not None:
                self._input_loop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._input_loop_task
                self._input_loop_task = None
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

    async def _periodic_inactivity_check(self) -> None:
        """Check for inactive threads every hour and suspend them."""
        while self._running:
            await asyncio.sleep(3600)  # Check every hour
            try:
                await self._suspend_inactive_threads()
            except Exception:
                logger.warning("Periodic inactivity check failed", exc_info=True)

    async def _periodic_heartbeat(self) -> None:
        """Broadcast heartbeat events to all subscribed clients.

        This prevents headless clients from timing out while the LLM is processing
        long requests. The heartbeat is only broadcast when a query is running.

        RFC-0013: Heartbeat is broadcast every 5 seconds.
        """
        from datetime import UTC, datetime

        from soothe.core.event_catalog import DaemonHeartbeatEvent

        while self._running:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_S)

            # Only send heartbeat when query is running (clients need it most)
            if not self._query_running:
                continue

            try:
                thread_id = self._runner.current_thread_id if self._runner else ""
                state = "running" if self._query_running else "idle"

                heartbeat = DaemonHeartbeatEvent(
                    thread_id=thread_id or "",
                    timestamp=datetime.now(UTC).isoformat(),
                    state=state,
                )

                # Broadcast to all subscribed clients via _broadcast
                if thread_id:
                    await self._broadcast(
                        {
                            "type": "event",
                            "thread_id": thread_id,
                            "namespace": [],
                            "mode": "custom",
                            "data": heartbeat.to_dict(),
                        }
                    )
            except Exception:
                logger.debug("Heartbeat broadcast failed (client disconnected)")

    async def _suspend_inactive_threads(self) -> None:
        """Suspend threads that have been inactive for longer than the configured timeout."""
        if not self._runner:
            return

        from datetime import datetime, timedelta

        from soothe.protocols.durability import ThreadFilter

        # Get timeout from config (in hours)
        timeout_hours = self._config.protocols.durability.thread_inactivity_timeout_hours
        timeout_threshold = datetime.now(tz=None) - timedelta(hours=timeout_hours)

        # Get all active threads
        active_threads = await self._runner.list_durability_threads(ThreadFilter(status="active"))

        suspended_count = 0
        for thread in active_threads:
            # Skip the currently active thread if it exists
            if (
                self._runner.current_thread_id
                and thread.thread_id == self._runner.current_thread_id
            ):
                continue

            # Check if thread has been inactive
            # Use updated_at (make naive for comparison if needed)
            updated_at = thread.updated_at
            if updated_at.tzinfo is not None:
                # Convert to naive datetime for comparison
                updated_at = updated_at.replace(tzinfo=None)
                threshold_with_tz = timeout_threshold.replace(tzinfo=None)
            else:
                threshold_with_tz = timeout_threshold

            if updated_at < threshold_with_tz:
                try:
                    thread_manager = self._runner.thread_context_manager()
                    await thread_manager.suspend_thread(thread.thread_id)
                    suspended_count += 1
                    logger.info(
                        "Suspended inactive thread %s (last updated: %s)",
                        thread.thread_id,
                        thread.updated_at,
                    )
                except Exception:
                    logger.warning(
                        "Failed to suspend inactive thread %s",
                        thread.thread_id,
                        exc_info=True,
                    )

        if suspended_count > 0:
            logger.info(
                "Suspended %d inactive threads (timeout: %d hours)", suspended_count, timeout_hours
            )

    async def stop(self) -> None:
        """Shut down the daemon gracefully."""
        self._readiness_state = "stopped"
        self._readiness_message = None
        self._running = False
        self._query_running = False

        if self._input_loop_task is not None and not self._input_loop_task.done():
            self._input_loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._input_loop_task
            self._input_loop_task = None

        # Cancel background tasks
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task

        if self._inactivity_check_task and not self._inactivity_check_task.done():
            self._inactivity_check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._inactivity_check_task

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task

        # Cancel any running query task
        if self._current_query_task and not self._current_query_task.done():
            self._current_query_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._current_query_task

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

        # Stop transport manager
        if self._transport_manager:
            await self._transport_manager.stop_all()

        # Cleanup clients
        for client in self._clients:
            with contextlib.suppress(Exception):
                client.writer.close()
                await client.writer.wait_closed()
        self._clients.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Shutdown default executor
        if hasattr(self, "_default_executor") and self._default_executor:
            self._default_executor.shutdown(wait=True)
            logger.debug("Default executor shut down")

        # Release singleton lock and clean up files
        if self._pid_lock_fd is not None:
            release_pid_lock(self._pid_lock_fd)
            self._pid_lock_fd = None
        else:
            cleanup_pid()
        logger.info("Soothe daemon stopped")

    # -- broadcast ----------------------------------------------------------

    async def _broadcast(self, msg: dict[str, Any]) -> None:
        """Route event to appropriate subscribers via event bus.

        Events with thread_id are routed to thread-specific topics.
        Events without thread_id are broadcast to all clients.

        Args:
            msg: Message dict to route. Must contain 'type' field.
        """
        msg_type = msg.get("type", "")

        # Extract thread_id for routing
        thread_id = msg.get("thread_id")

        # For status messages without thread_id, try current thread
        if not thread_id and msg_type == "status":
            thread_id = self._runner.current_thread_id if self._runner else None

        # Get event metadata for filtering (RFC-0022)
        from soothe.core.event_catalog import REGISTRY

        # For custom events, the actual event type is inside data["type"]
        event_type_for_meta = msg_type
        if msg_type == "event" and isinstance(msg.get("data"), dict):
            event_type_for_meta = msg["data"].get("type", msg_type)

        event_meta = REGISTRY.get_meta(event_type_for_meta) if event_type_for_meta else None

        if thread_id:
            # Route to thread-specific topic
            topic = f"thread:{thread_id}"
            await self._event_bus.publish(topic, msg, event_meta=event_meta)
        else:
            # Event without thread_id - broadcast to all transports
            logger.debug("Event has no thread_id, broadcasting to all: %s", msg_type)
            if self._transport_manager:
                await self._transport_manager.broadcast(msg)

    async def _send(self, client: _ClientConn, msg: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            client.writer.write(encode(msg))
            await client.writer.drain()

    def _handle_transport_message(self, client_id: str, msg: dict[str, Any]) -> None:
        """Handle incoming message from any transport.

        This method routes messages from the transport layer to the
        existing message handling logic.

        Args:
            client_id: Unique client identifier
            msg: Message dict from a transport client.
        """
        # Create a task to handle the message asynchronously
        task = asyncio.create_task(self._message_router.dispatch(client_id, msg))
        _ = task  # Suppress RUF006 warning - we intentionally don't track the task

    # -- static helpers -----------------------------------------------------

    @staticmethod
    def is_running() -> bool:
        """Check if a daemon is already running.

        Checks:
        1. PID file with valid process AND WebSocket port is live
        2. WebSocket port accepting connections (even without PID file)
        """
        from soothe.config import SootheConfig

        # Get WebSocket port from config
        try:
            cfg = SootheConfig()
            ws_host = cfg.daemon.transports.websocket.host
            ws_port = cfg.daemon.transports.websocket.port
        except Exception:
            ws_host = "127.0.0.1"
            ws_port = 8765

        # 1. Check PID file + verify WebSocket is live
        pf = pid_path()
        if pf.exists():
            try:
                pid = int(pf.read_text().strip())
                os.kill(pid, 0)
            except (ValueError, ProcessLookupError, PermissionError):
                cleanup_pid()
                # PID file stale, check port below
            else:
                # PID valid - but daemon must also have live WebSocket
                if SootheDaemon._is_port_live(ws_host, ws_port):
                    return True
                # PID valid but port dead - zombie daemon, cleanup needed
                cleanup_pid()
                return False

        # 2. Check WebSocket connectivity (primary indicator)
        return SootheDaemon._is_port_live(ws_host, ws_port)

    @staticmethod
    def find_pid() -> int | None:
        """Find the PID of a running daemon.

        Checks multiple indicators:
        1. PID file with valid process
        2. WebSocket port bound (if enabled)
        3. Process name scan for zombie daemons (fallback)

        Returns:
            PID if daemon is running, None otherwise.
        """
        from soothe.config import SootheConfig

        # 1. Check PID file first (fastest)
        pf = pid_path()
        if pf.exists():
            try:
                pid = int(pf.read_text().strip())
                os.kill(pid, 0)
            except (ValueError, ProcessLookupError, PermissionError):
                cleanup_pid()
                # Continue to check other indicators
            else:
                return pid

        # 2. Check WebSocket port (if enabled in default config)
        with contextlib.suppress(Exception):
            cfg = SootheConfig()
            if cfg.daemon.transports.websocket.enabled:
                ws_port = cfg.daemon.transports.websocket.port
                pid = SootheDaemon._find_port_process(ws_port)
                if pid:
                    return pid

        # 3. Fallback: check for daemon processes by name
        import subprocess

        pgrep_path = "/usr/bin/pgrep"
        with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            result = subprocess.run(
                [pgrep_path, "-f", "soothe.daemon"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                if pids:
                    return int(pids[0])

        return None

    @staticmethod
    def _find_port_process(port: int) -> int | None:
        """Find PID of process listening on a TCP port using lsof.

        Args:
            port: TCP port number.

        Returns:
            PID if found, None otherwise.
        """
        import subprocess

        try:
            result = subprocess.run(
                ["/usr/sbin/lsof", "-i", f"TCP:{port}", "-t", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                # lsof -t returns PIDs, one per line
                pids = result.stdout.strip().split("\n")
                if pids:
                    return int(pids[0])
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            pass
        return None

    @staticmethod
    def stop_running(timeout: float = _STOP_TIMEOUT_S) -> bool:
        """Send SIGTERM to the running daemon and wait for it to stop.

        Escalates to SIGKILL if the daemon does not exit within *timeout*
        seconds.

        Handles zombie daemons where PID file is missing but process still runs:
        1. First tries to stop via PID file
        2. If no PID file, checks ports and kills process holding them

        Args:
            timeout: Maximum seconds to wait before SIGKILL escalation.

        Returns:
            True if a signal was sent and daemon stopped, False if no daemon found.
        """
        from soothe.config import SootheConfig

        stopped = False
        pid: int | None = None

        # 1. Try to stop via PID file first
        pf = pid_path()
        if pf.exists():
            try:
                pid = int(pf.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                stopped = SootheDaemon._wait_for_pid_exit(pid, timeout)
            except (ValueError, ProcessLookupError, PermissionError):
                cleanup_pid()
                # Continue to check ports

        # 2. If PID file approach failed, check for zombie on ports
        if not stopped:
            with contextlib.suppress(Exception):
                cfg = SootheConfig()
                # Check WebSocket port
                if cfg.daemon.transports.websocket.enabled:
                    ws_port = cfg.daemon.transports.websocket.port
                    pid = SootheDaemon._find_port_process(ws_port)
                    if pid:
                        os.kill(pid, signal.SIGTERM)
                        stopped = SootheDaemon._wait_for_pid_exit(pid, timeout)

        # 3. Fallback: scan by process name for zombie daemons
        if not stopped:
            import subprocess

            pgrep_path = "/usr/bin/pgrep"
            with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, ValueError):
                # Find processes running soothe.daemon module
                result = subprocess.run(
                    [pgrep_path, "-f", "soothe.daemon"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip():
                    for pid_str in result.stdout.strip().split("\n"):
                        try:
                            pid = int(pid_str)
                            if pid != os.getpid():  # Don't kill ourselves
                                os.kill(pid, signal.SIGTERM)
                                stopped = SootheDaemon._wait_for_pid_exit(pid, timeout)
                                if stopped:
                                    break
                        except (ValueError, ProcessLookupError, PermissionError):
                            continue

        # 4. Cleanup regardless of outcome
        cleanup_pid()
        return stopped

    @staticmethod
    def _wait_for_pid_exit(pid: int, timeout: float) -> bool:
        """Wait for a process to exit, escalating to SIGKILL if needed.

        Args:
            pid: Process ID to wait for.
            timeout: Maximum seconds before SIGKILL escalation.

        Returns:
            True if process exited, False if still running.
        """
        import time

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                os.kill(pid, 0)
                time.sleep(0.2)
            except ProcessLookupError:
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
                return True

        return False
