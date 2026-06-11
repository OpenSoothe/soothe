"""Soothe daemon server - background agent runner with WebSocket IPC."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import threading
from dataclasses import dataclass
from typing import Any

from soothe.config import SootheConfig
from soothe.foundation.loop.state.persistence.manager import AgentLoopCheckpointPersistenceManager
from soothe.foundation.workspace import (
    cleanup_anonymous_workspaces,
    cleanup_legacy_per_loop_workspaces,
    resolve_daemon_workspace,
)
from soothe.logging import ThreadLogger
from soothe_sdk.client.protocol import encode

from soothe_daemon.bootstrap.logging import set_client_id, set_loop_id
from soothe_daemon.bootstrap.paths import pid_path
from soothe_daemon.bootstrap.singleton import (
    acquire_pid_lock,
    cleanup_pid,
    release_pid_lock,
)
from soothe_daemon.channel_manager import ChannelManager
from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.event import EventBus, EventSizeDistributionCollector, loop_event_topic
from soothe_daemon.protocol import MessageRouter
from soothe_daemon.query import QueryEngine
from soothe_daemon.runtime.loop_dispatcher import LoopInputDispatcher
from soothe_daemon.runtime.thread_state import ThreadStateRegistry
from soothe_daemon.server.handlers import DaemonHandlersMixin
from soothe_daemon.server.session import ClientSessionManager
from soothe_daemon.services.memory_profiler import MemoryProfiler

logger = logging.getLogger(__name__)

_CLEANUP_TIMEOUT_S = 3.0
_STOP_TIMEOUT_S = 8.0
_HEARTBEAT_INTERVAL_S = 5.0  # Broadcast heartbeat every 5 seconds


def _log_startup_banner(channel_manager: ChannelManager | None) -> None:
    """Log a clean startup banner with channel info.

    Args:
        channel_manager: The channel manager with started channels.
    """
    from soothe_daemon import __version__

    # Get channel details
    channels = channel_manager.get_channel_info() if channel_manager else []
    if channels:
        channel_str = " | ".join(f"{c['type']}: {c['client_count']} clients" for c in channels)
    else:
        channel_str = "none"

    # Compact single-line banner
    logger.info(
        "╭─ Soothe v%s ── channels: %s ──╯",
        __version__,
        channel_str,
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
        config: Agent ``SootheConfig`` (in-proc agent core, ``config.yml``).
        daemon_config: Daemon-server ``SootheDaemonConfig`` (transports,
            worker pool, distributed runner, ``daemon_config.yml``).
        handle_sigint_shutdown: Whether SIGINT should trigger daemon shutdown.
    """

    def __init__(
        self,
        config: SootheConfig | None = None,
        daemon_config: SootheDaemonConfig | None = None,
        *,
        handle_sigint_shutdown: bool = True,
    ) -> None:
        """Initialize the Soothe daemon.

        Args:
            config: Agent ``SootheConfig``.
            daemon_config: Daemon-server ``SootheDaemonConfig``.
            handle_sigint_shutdown: Whether SIGINT should trigger daemon shutdown.
                Disable for detached/background mode to avoid accidental Ctrl+C shutdown.
        """
        self._config = config or SootheConfig()
        self._daemon_config = daemon_config or SootheDaemonConfig()
        self._handle_sigint_shutdown = handle_sigint_shutdown

        # Shared persistence manager (avoids per-RPC pool creation/teardown)
        self._persistence_manager = AgentLoopCheckpointPersistenceManager(config=self._config)

        # Resolve daemon workspace (ephemeral TEMP unless SOOTHE_WORKSPACE set)
        self._daemon_workspace = resolve_daemon_workspace()
        logger.info("Daemon workspace: %s", self._daemon_workspace)

        # Migrate persisted workspaces from workspaces/ to data/workspaces/ (RFC-621)
        from soothe.foundation.workspace.migration import migrate_workspaces_to_data_dir

        migrate_workspaces_to_data_dir()

        # Incremental skill index (mtime-cached, global user skills only)
        from soothe.skills.index import SkillIndex

        self._skill_index = SkillIndex()

        self._clients: list[_ClientConn] = []
        self._server: asyncio.AbstractServer | None = None
        self._runner: Any = None
        # RFC-222 revised (Phase B): daemon-owned AutopilotService placeholder.
        # Constructed in start() with subscribe_to_bus=False to coexist with
        # the per-runner AutopilotService until Phase D retires that one.
        self._autopilot_service: Any = None  # AutopilotService | None
        self._running = False
        self._query_running = False  # Deprecated: use _active_threads instead
        self._current_query_task: asyncio.Task | None = None
        self._thread_stop = threading.Event()
        self._stop_event: asyncio.Event | None = None
        max_queue_size = self._daemon_config.max_input_queue_size
        self._loop_input_dispatcher = LoopInputDispatcher(self, max_queue_size=max_queue_size)
        self._cleanup_task: asyncio.Task[None] | None = None
        self._postgres_pool_task: asyncio.Task[None] | None = None
        self._inactivity_check_task: asyncio.Task[None] | None = None
        self._loop_gc_task: asyncio.Task[None] | None = None
        self._loop_status_reconciliation_task: asyncio.Task[None] | None = None
        self._stale_worker_reap_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._event_size_stats_task: asyncio.Task[None] | None = None
        self._event_bus_cleanup_task: asyncio.Task[None] | None = None  # IG-475
        # Smart heartbeat tracking (IG-426)
        self._last_broadcast_monotonic: float = 0.0
        # Message dispatch concurrency control (IG-258)
        self._dispatch_semaphore: asyncio.Semaphore = asyncio.Semaphore(
            self._daemon_config.max_concurrent_dispatches
        )
        _vmax = int(getattr(self._daemon_config, "max_concurrent_vision_preflight", 8) or 0)
        self._vision_preflight_semaphore: asyncio.Semaphore | None = (
            asyncio.Semaphore(_vmax) if _vmax > 0 else None
        )
        self._dispatch_tasks: dict[str, asyncio.Task] = {}  # client_id -> Task
        self._thread_logger: ThreadLogger | None = None
        self._pid_lock_fd: int | None = None
        # Channel manager for multi-channel support (RFC-620)
        self._channel_manager: ChannelManager | None = None
        # Event bus architecture (RFC-0013, IG-047)
        self._event_size_stats: EventSizeDistributionCollector | None = None
        if self._daemon_config.event_size_stats_enabled:
            self._event_size_stats = EventSizeDistributionCollector()
        self._event_bus: EventBus = EventBus(event_size_stats=self._event_size_stats)
        self._session_manager: ClientSessionManager = ClientSessionManager(
            self._event_bus,
            cancel_callback=self._cancel_loop_for_session,
            dispatch_cleanup_callback=self._cleanup_dispatch_tasks,  # IG-258
            config=self._config,  # RFC-614: for streaming interval config
        )
        # Keys: LangGraph checkpoint id (``configurable.thread_id``), not ``loop_id``.
        self._active_threads: dict[str, asyncio.Task] = {}
        #: Loop ids for all in-flight streams (heartbeats; internal only).
        self._active_stream_loop_ids: set[str] = set()
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
        # MCP registry (RFC-412): daemon-singleton for MCP connections
        self._mcp_registry: Any = None  # MCPRegistry | None
        # Per-loop display card ledger (RFC-413).
        from soothe_daemon.display import LoopCardManager

        self._card_manager: LoopCardManager = LoopCardManager(self)
        # IG-475: Memory profiler (tracemalloc) for leak detection
        self._memory_profiler: MemoryProfiler | None = None
        if self._daemon_config.memory_profiling.enabled:
            self._memory_profiler = MemoryProfiler(self._daemon_config.memory_profiling)

    async def _cancel_loop_for_session(self, loop_id: str) -> None:
        """Cancel in-flight work for a loop when a client disconnects (IG-408)."""
        if not str(loop_id or "").strip():
            logger.warning("[Session] cancel_callback with empty loop_id; ignoring")
            return
        qe = getattr(self, "_query_engine", None)
        if qe is not None:
            await qe.cancel_loop(loop_id)

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Start the daemon server using the transport manager."""
        from concurrent.futures import ThreadPoolExecutor

        from soothe.runner import SootheRunner

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

            # RFC-221: apply env overrides (e.g. SOOTHE_DISTRIBUTED) before factory init
            from soothe_daemon.config import apply_env_overrides

            apply_env_overrides(self._daemon_config)

            # RFC-221: keep a utility SootheRunner for non-streaming ops
            # (create_persisted_thread, touch_thread_activity_timestamp, etc.).
            # Streaming is handled per-loop by LoopRunnerFactory — this instance
            # is never passed to astream().
            from soothe.runner import SootheRunner

            try:
                self._runner = await asyncio.to_thread(SootheRunner, self._config)
            except Exception as exc:
                self._readiness_state = "error"
                self._readiness_message = str(exc)
                raise

            # RFC-221: LoopRunnerFactory creates one subprocess runner per loop_id.
            # Construct it BEFORE AutopilotService — the autopilot wraps it.
            from soothe_daemon.runner.factory import LoopRunnerFactory

            try:
                self._runner_factory = LoopRunnerFactory(self._daemon_config, self._config)
            except Exception as exc:
                self._readiness_state = "error"
                self._readiness_message = str(exc)
                raise

            # RFC-222 revised (Phase C): daemon-owned AutopilotService with
            # full real-dispatch wiring. Constructs its OWN GoalEngine and
            # InternalEventBus (not the singleton/runner's) so its DAG state
            # and event subscriptions are isolated from the per-runner
            # AutopilotService that handles autonomous mode in subprocess.
            #
            # The daemon-owned instance is the one HTTP /autopilot/submit
            # talks to (Phase C5 cutover). Its scheduling loop dispatches
            # to subprocess workers via the runner_factory above.
            try:
                from soothe.backends.persistence import create_persist_store
                from soothe.foundation.autopilot.engine import GoalEngine
                from soothe.foundation.autopilot.service import (
                    AutopilotService,
                    ContextProjector,
                    DurabilityGoalDispatchContextStore,
                    WorkspaceReservation,
                )
                from soothe.foundation.events.internal_bus import InternalEventBus
                from soothe_sdk.client.config import SOOTHE_DATA_DIR

                # Isolated bus for the daemon's autopilot domain.
                daemon_autopilot_bus = InternalEventBus()
                # Isolated GoalEngine — separate DAG from the runner's autonomous mode.
                daemon_goal_engine = GoalEngine(
                    max_retries=self._config.agent.autonomous.max_retries,
                    config=self._config,
                    internal_bus=daemon_autopilot_bus,
                )
                ws_cfg = self._config.agent.autonomous.workspace_reservation
                workspace_reservation = WorkspaceReservation(
                    enabled=ws_cfg.enabled,
                    strict_overlap=ws_cfg.strict_overlap,
                )

                dur_backend = self._config.resolve_durability_backend()
                dur_cfg = self._config.agent.protocols.durability
                persist_dir = dur_cfg.persist_dir or str(SOOTHE_DATA_DIR)
                if dur_backend == "postgresql":
                    dsn = self._config.resolve_postgres_dsn_for_database("metadata")
                    goal_persist_store = create_persist_store(
                        backend="postgresql",
                        dsn=dsn,
                        namespace="autopilot_goals",
                    )
                    context_persist_store = create_persist_store(
                        backend="postgresql",
                        dsn=dsn,
                        namespace="autopilot_context",
                    )
                else:
                    goal_persist_store = create_persist_store(
                        persist_dir=persist_dir,
                        backend="sqlite",
                        namespace="autopilot_goals",
                    )
                    context_persist_store = create_persist_store(
                        persist_dir=persist_dir,
                        backend="sqlite",
                        namespace="autopilot_context",
                    )

                consensus_model = None
                try:
                    consensus_model = self._config.create_chat_model("think")
                except Exception:
                    logger.warning(
                        "[Autopilot] consensus model unavailable; "
                        "completed goals will suspend until model is configured"
                    )

                self._autopilot_service = AutopilotService(
                    goal_engine=daemon_goal_engine,
                    config=self._config.agent.autonomous,
                    internal_bus=daemon_autopilot_bus,
                    subscribe_to_bus=True,
                    runner_factory=self._runner_factory,
                    workspace_reservation=workspace_reservation,
                    consensus_model=consensus_model,
                    goal_persist_store=goal_persist_store,
                )
                if context_persist_store is not None:
                    self._autopilot_service._context_store = DurabilityGoalDispatchContextStore(
                        context_persist_store
                    )
                else:
                    from soothe.foundation.autopilot.service import InMemoryGoalDispatchContextStore

                    self._autopilot_service._context_store = InMemoryGoalDispatchContextStore()
                self._autopilot_service._context_projector = ContextProjector(
                    self._autopilot_service._context_store,
                    self._config.agent.autonomous.context_projection,
                )
                logger.info(
                    "[Autopilot] daemon-owned AutopilotService constructed "
                    "(real dispatch enabled; scheduling loop will start)"
                )

                # RFC-228: Bridge internal autopilot events to client-visible events
                # for desktop clients with autopilot_subscribed=True
                from soothe.foundation.events.internal_events import internal_to_client_event

                async def _bridge_internal_to_client(event: Any) -> None:
                    """Bridge internal event to client-visible event for autopilot subscribers."""
                    # Convert internal event to client-visible format
                    client_event = internal_to_client_event(event)
                    if client_event is None:
                        return
                    # Publish to autopilot topic for subscribed clients
                    await self._event_bus.publish(
                        "autopilot",
                        client_event.model_dump(mode="json"),
                        event_meta=None,
                    )

                # Subscribe bridge to internal bus (forward relevant events)
                daemon_autopilot_bus.subscribe("*", _bridge_internal_to_client)
            except Exception:
                # Construction must never block daemon startup. Log loudly;
                # autopilot endpoints will return 503.
                logger.exception("[Autopilot] failed to construct daemon-owned AutopilotService")
                self._autopilot_service = None

            # Reap orphaned worker_pool subprocesses left after crashes / restarts.
            try:
                from soothe_daemon.persistence import reap_stale_soothe_worker_processes

                reap_stale_soothe_worker_processes()
            except Exception:
                logger.debug("Stale worker process cleanup skipped", exc_info=True)

            # RFC-221: pre-warm runner pool (worker_pool or thread_pool).
            if self._daemon_config.worker_pool.enabled or self._daemon_config.thread_pool.enabled:
                try:
                    await self._runner_factory.initialize_pool()
                except Exception as exc:
                    self._readiness_state = "error"
                    self._readiness_message = str(exc)
                    raise

            # Pre-open shared PostgreSQL pools in thread_pool mode.
            try:
                from soothe_daemon.persistence.pools import preopen_shared_postgres_pools

                await preopen_shared_postgres_pools(self._config, self._daemon_config)
            except Exception:
                logger.warning(
                    "Failed to pre-open shared PostgreSQL pools at startup",
                    exc_info=True,
                )

            # RFC-412: Initialize MCP registry (daemon-singleton)
            if self._config.mcp_servers:
                try:
                    from soothe.mcp.registry import MCPRegistry

                    self._mcp_registry = MCPRegistry(
                        servers=self._config.mcp_servers,
                        secret_resolver=self._config.secret_resolver,
                    )
                    await self._mcp_registry.initialize()
                    logger.info(
                        "[MCP] Registry initialized with %d server(s)",
                        len(self._config.mcp_servers),
                    )
                except Exception:
                    logger.warning("[MCP] Failed to initialize registry", exc_info=True)
                    self._mcp_registry = None

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

            self._channel_manager = ChannelManager(
                self._daemon_config,
                event_bus=self._event_bus,
                runner=self._runner,
                soothe_config=self._config,
                session_manager=self._session_manager,
                autopilot_service=self._autopilot_service,
                memory_profiler=self._memory_profiler,
            )
            self._channel_manager.set_message_handler(self._handle_transport_message)
            self._channel_manager.set_handshake_callback(self._get_handshake_messages)
            await self._channel_manager.start_all()

            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            from soothe_daemon.persistence.pools import uses_postgresql_persistence

            if uses_postgresql_persistence(self._config):
                self._postgres_pool_task = asyncio.create_task(
                    self._periodic_postgres_pool_maintenance()
                )
            self._inactivity_check_task = asyncio.create_task(self._periodic_inactivity_check())
            gc_cfg = self._daemon_config.loop_gc
            if gc_cfg.enabled:
                self._loop_gc_task = asyncio.create_task(self._periodic_loop_gc())
            recon_cfg = self._daemon_config.loop_status_reconciliation
            if recon_cfg.enabled:
                self._loop_status_reconciliation_task = asyncio.create_task(
                    self._periodic_loop_status_reconciliation()
                )
            reap_cfg = self._daemon_config.stale_worker_reap
            if self._daemon_config.worker_pool.enabled and reap_cfg.enabled:
                self._stale_worker_reap_task = asyncio.create_task(
                    self._periodic_stale_worker_reap()
                )
            self._heartbeat_task = asyncio.create_task(self._periodic_heartbeat())
            self._queue_monitoring_task: asyncio.Task[None] = asyncio.create_task(
                self._periodic_queue_monitoring()
            )
            # IG-475: Periodic event bus cleanup to remove orphaned topics
            self._event_bus_cleanup_task = asyncio.create_task(self._periodic_event_bus_cleanup())
            if self._event_size_stats is not None:
                self._event_size_stats_task = asyncio.create_task(self._periodic_event_size_stats())

            # Detect incomplete threads from previous daemon run (RFC-0010)
            await self._detect_incomplete_threads()

            await self._broadcast(
                {
                    "type": "status",
                    "state": "idle",
                }
            )

            # RFC-222 revised (Phase C): start the daemon-owned AutopilotService's
            # scheduling loop so HTTP /autopilot/submit submissions get dispatched.
            # Failure to start is logged but does not block the daemon — autopilot
            # endpoints will return 503-equivalent until the next restart.
            # Only start if config.agent.autonomous.enabled is True.
            if self._autopilot_service is not None and self._config.agent.autonomous.enabled:
                try:
                    await self._autopilot_service.start()
                    logger.info("[Autopilot] scheduling loop started (enabled=true)")
                except Exception:
                    logger.exception("[Autopilot] failed to start scheduling loop")
            elif self._autopilot_service is not None:
                logger.info(
                    "[Autopilot] service constructed but scheduling loop NOT started "
                    "(config.agent.autonomous.enabled=false)"
                )

            self._readiness_state = "ready"
            self._readiness_message = None

            # IG-475: Start memory profiler if enabled
            if self._memory_profiler is not None:
                self._memory_profiler.start()

            # Log startup banner with channel info
            _log_startup_banner(self._channel_manager)
        except Exception as exc:
            # Startup failed - cleanup and release PID lock
            self._readiness_state = "error"
            self._readiness_message = str(exc)
            logger.exception("Daemon startup failed")

            # Stop any partially initialized resources
            if self._channel_manager:
                await self._channel_manager.stop_all()
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
            "input_history": [],
        }
        return [initial_msg, self.daemon_ready_message()]

    @staticmethod
    def _is_port_live(host: str, port: int) -> bool:
        """Check if a WebSocket server is accepting connections.

        Uses socket probe first (fast), falls back to lsof if needed.

        Args:
            host: Host address to check.
            port: TCP port number.

        Returns:
            True if port is accepting connections, False otherwise.
        """
        import socket as sock_mod

        # Primary: socket probe (fastest - no subprocess spawn)
        try:
            s = sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_STREAM)
            s.settimeout(0.1)  # 100ms is sufficient for local check
            s.connect((host, port))
            s.close()
            return True
        except (ConnectionRefusedError, OSError, TimeoutError):
            pass  # Fall back to lsof

        # Fallback: lsof for cases where socket probe fails but port is bound
        import subprocess

        with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            result = subprocess.run(
                ["lsof", "-i", f"TCP:{port}", "-t", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=0.2,  # 200ms timeout
                check=False,
            )
            return result.returncode == 0 and result.stdout.strip()

        return False

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
        import re
        from datetime import datetime, timedelta

        try:
            auto_cancel = self._daemon_config.auto_cancel_on_startup
            max_age_hours = self._daemon_config.thread_max_age_hours
            max_age_threshold = (
                datetime.now(tz=None) - timedelta(hours=max_age_hours) if auto_cancel else None
            )

            rows = await self._persistence_manager.list_loops(status_filter="running")

            incomplete = []
            for row in rows:
                loop_info = {
                    "loop_id": row["loop_id"],
                    "thread_ids": row.get("thread_ids", []),
                    "current_thread_id": row.get("current_thread_id", ""),
                    "status": row.get("status", ""),
                    "total_goals_completed": row.get("total_goals_completed", 0),
                    "updated_at": row.get("updated_at"),
                }
                incomplete.append(loop_info)

                # Auto-cancel very old loops (IG-138)
                if auto_cancel and max_age_threshold and loop_info["updated_at"]:
                    try:
                        updated_str = loop_info["updated_at"]
                        if isinstance(updated_str, str):
                            normalized = re.sub(r"Z$", "+00:00", updated_str)
                            try:
                                updated_at = datetime.fromisoformat(normalized)
                            except ValueError:
                                logger.debug(
                                    "Failed to parse timestamp: %s for loop %s",
                                    updated_str,
                                    loop_info["loop_id"],
                                )
                                continue
                            if updated_at.tzinfo is not None:
                                updated_at = updated_at.replace(tzinfo=None)
                        else:
                            continue

                        if updated_at < max_age_threshold:
                            loop_id = loop_info["loop_id"]
                            age_hours = (datetime.now(tz=None) - updated_at).total_seconds() / 3600
                            logger.warning(
                                "Auto-cancelling very old loop %s (age: %.1f hours > max: %d)",
                                loop_id,
                                age_hours,
                                max_age_hours,
                            )
                            logger.info(
                                "Loop %s marked for cancellation (age exceeds threshold)",
                                loop_id,
                            )
                    except (ValueError, TypeError):
                        logger.debug("Failed to parse timestamp for loop %s", loop_info["loop_id"])
                        continue

            if incomplete:
                remaining = [
                    t
                    for t in incomplete
                    if t["loop_id"] not in getattr(self, "_cancelled_threads", set())
                ]
                if remaining:
                    logger.info(
                        "Found %d incomplete loops from previous run (%d auto-cancelled)",
                        len(remaining),
                        len(incomplete) - len(remaining),
                    )
                    for t in remaining:
                        # Set loop_id context for full ID in daemon.log
                        set_loop_id(t["loop_id"])
                        logger.info(
                            "Loop %s: %d goals completed, %d threads",
                            t["loop_id"],
                            t["total_goals_completed"],
                            len(t["thread_ids"]),
                        )
            else:
                logger.debug("No incomplete loops found from previous runs")
        except Exception:
            logger.debug("Incomplete thread detection failed", exc_info=True)

    async def serve_forever(self) -> None:
        """Block until the daemon is stopped.

        Supports both signal-based shutdown (main thread) and thread-safe
        shutdown via ``request_stop()`` (background thread).
        """
        # With multi-channel architecture, we don't need self._server
        # The channel manager handles all servers
        if not self._channel_manager and not self._server:
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

        try:
            await self._stop_event.wait()
        finally:
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

    async def _periodic_postgres_pool_maintenance(self) -> None:
        """Release idle connections on shared daemon pools (every 5 minutes)."""
        from soothe_daemon.persistence.pools import periodic_postgres_pool_maintenance

        await periodic_postgres_pool_maintenance(is_running=lambda: self._running)

    async def _periodic_stale_worker_reap(self) -> None:
        """Reap orphaned worker_pool subprocesses on a fixed interval."""
        from soothe_daemon.persistence.process_cleanup import periodic_stale_worker_reap

        reap_cfg = self._daemon_config.stale_worker_reap
        await periodic_stale_worker_reap(
            is_running=lambda: self._running,
            interval_s=reap_cfg.interval_seconds,
            daemon_pid=os.getpid(),
        )

    async def _periodic_inactivity_check(self) -> None:
        """Check for inactive threads every hour and suspend them."""
        while self._running:
            await asyncio.sleep(3600)  # Check every hour
            try:
                await self._suspend_inactive_threads()
            except Exception:
                logger.warning("Periodic inactivity check failed", exc_info=True)

    async def _periodic_loop_gc(self) -> None:
        """Periodic loop GC: ephemeral pass + empty-loop pass per tick (IG-466).

        Both passes share the per-loop purge helper. Loops appearing in both
        listings are purged once via de-duplication by ``loop_id``.
        """
        from datetime import UTC, datetime, timedelta

        from soothe_daemon.runtime.loop_gc import purge_loop_execution_data

        gc_cfg = self._daemon_config.loop_gc
        interval = float(gc_cfg.interval_seconds)
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            try:
                now = datetime.now(UTC)
                idle_before_ephemeral = now - timedelta(hours=gc_cfg.ephemeral_idle_hours)
                idle_before_empty = now - timedelta(hours=gc_cfg.empty_idle_hours)

                expired_ephemeral = await self._persistence_manager.list_expired_ephemeral_loops(
                    idle_before_ephemeral,
                    limit=gc_cfg.batch_size,
                )
                empty_loops = await self._persistence_manager.list_empty_loops(
                    idle_before_empty,
                    limit=gc_cfg.batch_size,
                )
                if not expired_ephemeral and not empty_loops:
                    continue

                seen: set[str] = set()
                purged_ephemeral = 0
                purged_empty = 0

                for row in expired_ephemeral:
                    loop_id = str(row.get("loop_id") or "").strip()
                    if not loop_id or loop_id in seen:
                        continue
                    seen.add(loop_id)
                    if await purge_loop_execution_data(self, loop_id, row):
                        purged_ephemeral += 1

                for row in empty_loops:
                    loop_id = str(row.get("loop_id") or "").strip()
                    if not loop_id or loop_id in seen:
                        continue
                    seen.add(loop_id)
                    if await purge_loop_execution_data(self, loop_id, row):
                        purged_empty += 1

                if purged_ephemeral or purged_empty:
                    logger.info(
                        "Loop GC purged %d ephemeral, %d empty "
                        "(idle thresholds: ephemeral=%dh, empty=%dh)",
                        purged_ephemeral,
                        purged_empty,
                        gc_cfg.ephemeral_idle_hours,
                        gc_cfg.empty_idle_hours,
                    )
            except Exception:
                logger.warning("Loop GC failed", exc_info=True)

    async def _periodic_loop_status_reconciliation(self) -> None:
        """Demote stale ``status="running"`` rows whose runner is no longer active.

        A loop row qualifies as stale when ALL hold:
          * ``status == "running"``
          * ``updated_at`` older than ``stale_running_seconds``
          * ``loop_id`` is NOT in this daemon's ``_active_stream_loop_ids``

        The runner heartbeat (see ``_runner_agentic._start_loop_heartbeat``)
        ticks ``updated_at`` every ~30s while a goal is in flight, so loops
        that miss multiple heartbeat windows are presumed orphaned (daemon
        crash + restart, runner subprocess crash, etc.) and are demoted to
        ``idle`` so list_loops reflects reality.
        """
        from datetime import UTC, datetime, timedelta

        cfg = self._daemon_config.loop_status_reconciliation
        interval = float(cfg.interval_seconds)
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            try:
                stale_before = datetime.now(UTC) - timedelta(seconds=cfg.stale_running_seconds)
                rows = await self._persistence_manager.list_loops(
                    status_filter="running",
                    limit=cfg.batch_size,
                )
                if not rows:
                    continue

                active_set: set[str] = set(self._active_stream_loop_ids)
                demoted = 0
                for row in rows:
                    loop_id = str(row.get("loop_id") or "").strip()
                    if not loop_id or loop_id in active_set:
                        continue
                    updated_at_raw = row.get("updated_at")
                    if not isinstance(updated_at_raw, str) or not updated_at_raw:
                        continue
                    try:
                        # SQLite stores ISO with offset; PG list_loops returns isoformat too.
                        updated_at = datetime.fromisoformat(updated_at_raw.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=UTC)
                    if updated_at >= stale_before:
                        continue
                    try:
                        await self._persistence_manager.update_loop_metadata(loop_id, status="idle")
                        demoted += 1
                        logger.info(
                            "Reconciled stale loop status: %s running -> idle "
                            "(last updated %s, threshold %ds, no active runner)",
                            loop_id,
                            updated_at_raw,
                            cfg.stale_running_seconds,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to demote stale loop %s",
                            loop_id,
                            exc_info=True,
                        )
                if demoted:
                    logger.info(
                        "Loop status reconciliation: demoted %d stale running loop(s)",
                        demoted,
                    )
            except Exception:
                logger.warning("Loop status reconciliation failed", exc_info=True)

    async def _periodic_event_size_stats(self) -> None:
        """Log EventBus wire-size distribution on a fixed interval (IG-403).

        Stops emitting while no events have been published for
        ``event_size_stats_idle_pause_seconds`` (window is discarded without logging).
        """
        stats = self._event_size_stats
        if stats is None:
            return
        interval = float(self._daemon_config.event_size_stats_interval_seconds)
        idle_pause = float(self._daemon_config.event_size_stats_idle_pause_seconds)
        while self._running:
            await asyncio.sleep(interval)
            try:
                stats.emit_log_if_active(idle_pause_seconds=idle_pause, log_fn=logger.info)
            except Exception:
                logger.debug("event_size_stats periodic tick failed", exc_info=True)

    async def _periodic_event_bus_cleanup(self) -> None:
        """Periodically clean up orphaned event bus topics (IG-475).

        Removes topics with no subscribers that were not properly cleaned up
        during unsubscribe (e.g., due to race conditions or early disconnects).
        Runs every 60 seconds to minimize memory overhead.
        """
        while self._running:
            await asyncio.sleep(60)  # Check every 60 seconds
            try:
                removed = await self._event_bus.cleanup_orphaned_topics()
                if removed > 0:
                    logger.info("Event bus cleanup: removed %d orphaned topics", removed)
            except Exception:
                logger.debug("Event bus cleanup failed", exc_info=True)

    async def _periodic_queue_monitoring(self) -> None:
        """Monitor queue depths and log warnings when near capacity (IG-258)."""
        while self._running:
            await asyncio.sleep(10)  # Check every 10 seconds
            try:
                # Check input queue depth
                max_queue_size = self._daemon_config.max_input_queue_size
                if max_queue_size > 0:  # Only check if limit is set
                    current_size = self._loop_input_dispatcher.total_queued()
                    threshold = int(max_queue_size * 0.8)  # 80% threshold
                    if current_size > threshold:
                        logger.warning(
                            "Loop input queues near capacity: %d/%d (%.1f%%)",
                            current_size,
                            max_queue_size,
                            (current_size / max_queue_size) * 100,
                        )

                # Check event queue depths per client
                if self._session_manager:
                    async with self._session_manager._lock:
                        for client_id, session in self._session_manager._sessions.items():
                            event_queue_size = session.event_queue.qsize()
                            event_queue_max = 10000  # Default maxsize
                            event_threshold = int(event_queue_max * 0.8)
                            if event_queue_size > event_threshold:
                                # Set client_id context for full ID in daemon.log
                                set_client_id(client_id)
                                logger.warning(
                                    "Client %s event queue near capacity: %d/%d (%.1f%%)",
                                    client_id,
                                    event_queue_size,
                                    event_queue_max,
                                    (event_queue_size / event_queue_max) * 100,
                                )
            except Exception:
                logger.warning("Periodic queue monitoring failed", exc_info=True)

    async def _periodic_heartbeat(self) -> None:
        """Broadcast heartbeat events to all subscribed clients.

        This prevents headless clients from timing out while the LLM is processing
        long requests. The heartbeat is only broadcast when a query is running.

        RFC-0013: Heartbeat is broadcast every 5 seconds.
        IG-426: Skip heartbeat if stream is actively flowing (last broadcast < 5s).
        """
        from datetime import UTC, datetime
        from time import monotonic

        from soothe.foundation.events import DaemonHeartbeatEvent

        while self._running:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_S)

            # Only send heartbeat when query is running (clients need it most)
            if not self._query_running:
                continue

            # Smart heartbeat: skip if stream actively flowing (IG-426)
            now = monotonic()
            if now - self._last_broadcast_monotonic < _HEARTBEAT_INTERVAL_S:
                # Stream is active, heartbeat not needed
                continue

            try:
                state = "running" if self._query_running else "idle"
                active_loop_ids = set(self._active_stream_loop_ids)  # snapshot

                # Event payload field is legacy; routing uses envelope ``loop_id`` (IG-408).
                heartbeat = DaemonHeartbeatEvent(
                    thread_id="",
                    timestamp=datetime.now(UTC).isoformat(),
                    state=state,
                )

                for loop_id in active_loop_ids:
                    await self._broadcast(
                        {
                            "type": "event",
                            "loop_id": loop_id,
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
        timeout_hours = self._config.agent.protocols.durability.thread_inactivity_timeout_hours
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

        # IG-475: Stop memory profiler if running
        if self._memory_profiler is not None:
            self._memory_profiler.stop()

        # RFC-222 revised (Phase C): stop the autopilot scheduling loop early
        # so it doesn't dispatch new goals while the rest of the daemon shuts down.
        if self._autopilot_service is not None:
            try:
                await self._autopilot_service.stop(reason="shutdown")
            except Exception:
                logger.warning("[Autopilot] stop raised during shutdown", exc_info=True)

        await self._loop_input_dispatcher.shutdown()

        # Cancel background tasks
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task

        if self._postgres_pool_task and not self._postgres_pool_task.done():
            self._postgres_pool_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._postgres_pool_task

        if self._inactivity_check_task and not self._inactivity_check_task.done():
            self._inactivity_check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._inactivity_check_task
        if self._loop_gc_task and not self._loop_gc_task.done():
            self._loop_gc_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_gc_task
        if (
            self._loop_status_reconciliation_task
            and not self._loop_status_reconciliation_task.done()
        ):
            self._loop_status_reconciliation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_status_reconciliation_task

        if self._stale_worker_reap_task and not self._stale_worker_reap_task.done():
            self._stale_worker_reap_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stale_worker_reap_task

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task

        if hasattr(self, "_queue_monitoring_task") and not self._queue_monitoring_task.done():
            self._queue_monitoring_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._queue_monitoring_task

        if self._event_size_stats_task and not self._event_size_stats_task.done():
            self._event_size_stats_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._event_size_stats_task
            self._event_size_stats_task = None

        # IG-475: Cancel event bus cleanup task
        if self._event_bus_cleanup_task and not self._event_bus_cleanup_task.done():
            self._event_bus_cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._event_bus_cleanup_task
            self._event_bus_cleanup_task = None

        # Cancel any running query task
        if self._current_query_task and not self._current_query_task.done():
            self._current_query_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._current_query_task

        # IG-248: Skip stopped status broadcast - daemon shutdown disconnects all clients anyway
        # No need to broadcast globally; clients will receive connection close event

        # Clean up runner resources with a timeout
        if self._runner and hasattr(self._runner, "cleanup"):
            try:
                await asyncio.wait_for(self._runner.cleanup(), timeout=_CLEANUP_TIMEOUT_S)
            except TimeoutError:
                logger.warning("Runner cleanup timed out after %.1fs", _CLEANUP_TIMEOUT_S)
            except Exception:
                logger.debug("Failed to cleanup runner", exc_info=True)

        # RFC-221 enhancement: shutdown runner pool and shared PG pools
        if hasattr(self, "_runner_factory") and self._runner_factory:
            try:
                await self._runner_factory.shutdown_pool()
            except Exception:
                logger.debug("Failed to shutdown runner pool", exc_info=True)

        # RFC-412: Shutdown MCP registry
        if self._mcp_registry is not None:
            try:
                await self._mcp_registry.shutdown(deadline_seconds=_CLEANUP_TIMEOUT_S)
                logger.info("[MCP] Registry shutdown complete")
            except Exception:
                logger.warning("[MCP] Registry shutdown error", exc_info=True)

        try:
            from soothe_daemon.persistence import reap_stale_soothe_worker_processes

            reap_stale_soothe_worker_processes()
        except Exception:
            logger.debug("Stale worker cleanup on shutdown skipped", exc_info=True)

        # Close shared persistence manager
        with contextlib.suppress(Exception):
            await self._persistence_manager.close()

        # Clean up anonymous workspace directories
        cleanup_anonymous_workspaces()
        cleanup_legacy_per_loop_workspaces()

        # Stop channel manager
        if self._channel_manager:
            await self._channel_manager.stop_all()

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
        """Route events to loop subscribers (and global only for explicit daemon-wide messages).

        Client-visible delivery is keyed strictly by ``loop_id`` on the message envelope.
        Internal CoreAgent ``thread_id`` is not used to infer routing.
        """
        # Track last broadcast for smart heartbeat (IG-426)
        from time import monotonic

        self._last_broadcast_monotonic = monotonic()

        msg_type = msg.get("type", "")
        lid = str(msg.get("loop_id") or "").strip()

        from soothe.foundation.events import REGISTRY
        from soothe.foundation.events.visibility import (
            decide_client_wire_visibility,
            event_type_from_wire_message,
        )

        event_type_for_meta = event_type_from_wire_message(msg) or msg_type
        event_meta = REGISTRY.get_meta(event_type_for_meta) if event_type_for_meta else None
        decision = decide_client_wire_visibility(msg, event_meta=event_meta)
        if not decision.visible:
            suppressed = getattr(self, "_internal_events_suppressed", 0) + 1
            self._internal_events_suppressed = suppressed
            if suppressed % 500 == 1:
                logger.debug(
                    "Suppressing non-client-visible event broadcast "
                    "(type=%s, kind=%s, reason=%s, total=%d)",
                    event_type_for_meta,
                    decision.kind.value,
                    decision.reason,
                    suppressed,
                )
            return

        if lid:
            await self._event_bus.publish(loop_event_topic(lid), msg, event_meta=event_meta)
            await self._session_manager.wake_senders_for_loop(lid)
            return

        # Unscoped daemon-wide frames only (never infer scope from thread_id).
        if msg_type == "status" and msg.get("state") in ("idle", "ready", "stopped", "detached"):
            await self._event_bus.publish("global", msg, event_meta=None)
            return

        if msg_type == "command_response":
            await self._event_bus.publish("global", msg, event_meta=None)
            return

        logger.warning(
            "Dropping broadcast: missing loop_id for scoped delivery (type=%s, state=%s)",
            msg_type,
            msg.get("state"),
        )

    async def _send(self, client: _ClientConn, msg: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            client.writer.write(encode(msg))
            await client.writer.drain()

    def _handle_transport_message(self, client_id: str, msg: dict[str, Any]) -> None:
        """Handle incoming message from any transport.

        This method routes messages from the transport layer to the
        existing message handling logic with concurrency control (IG-258).

        Args:
            client_id: Unique client identifier
            msg: Message dict from a transport client.
        """
        # Create a task with semaphore control and tracking (IG-258)
        task = asyncio.create_task(self._dispatch_with_semaphore(client_id, msg))
        # Track task per client for cleanup on disconnect
        self._dispatch_tasks[client_id] = task
        # Auto-cleanup when task completes
        task.add_done_callback(lambda t: self._dispatch_tasks.pop(client_id, None))

    async def _dispatch_with_semaphore(self, client_id: str, msg: dict[str, Any]) -> None:
        """Dispatch message with semaphore control and proper cleanup (IG-258).

        Args:
            client_id: Unique client identifier
            msg: Message dict from a transport client.
        """
        async with self._dispatch_semaphore:
            try:
                await self._message_router.dispatch(client_id, msg)
            except asyncio.CancelledError:
                logger.debug("Dispatch cancelled for client %s", client_id)
                raise
            except Exception:
                logger.exception("Error dispatching message for client %s", client_id)

    async def _cleanup_dispatch_tasks(self, client_id: str) -> None:
        """Cancel pending dispatch tasks for disconnected client (IG-258).

        Args:
            client_id: Client identifier being disconnected
        """
        # Set client_id context for full ID in daemon.log
        set_client_id(client_id)
        if client_id in self._dispatch_tasks:
            task = self._dispatch_tasks[client_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass  # Expected cancellation
            logger.debug("Cancelled dispatch task for client %s", client_id)

    # -- static helpers -----------------------------------------------------

    @staticmethod
    def is_running() -> bool:
        """Check if a daemon is already running.

        Checks:
        1. PID file with valid process (fast, no config loading)
        2. WebSocket port accepting connections (fallback)
        """
        # Use default port - avoid config loading for speed
        ws_host = "127.0.0.1"
        ws_port = 8765

        # 1. Check PID file first (fastest)
        pf = pid_path()
        if pf.exists():
            try:
                pid = int(pf.read_text().strip())
                os.kill(pid, 0)  # Check process exists
            except (ValueError, ProcessLookupError, PermissionError):
                cleanup_pid()
                # PID file stale, check port below
            else:
                # PID valid - process is running, trust it
                return True

        # 2. Check WebSocket port (fallback when no PID file)
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

        # 2. Check WebSocket port (use default, skip config loading)
        pid = SootheDaemon._find_port_process(8765)
        if pid:
            return pid

        # 3. Fallback: check for daemon processes by name
        # Use specific pattern to match main daemon entrypoint only, not worker subprocesses.
        # Worker subprocesses have "pool_runner" or "_pool_worker" in their command line.
        import subprocess

        pgrep_path = "/usr/bin/pgrep"
        with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            result = subprocess.run(
                [pgrep_path, "-f", "python.*-m soothe_daemon"],
                capture_output=True,
                text=True,
                timeout=0.5,  # 500ms timeout
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                # Filter out worker subprocesses (they have pool_runner in cmdline)
                for pid_str in pids:
                    try:
                        pid = int(pid_str)
                        # Verify this is main daemon, not a worker subprocess
                        cmdline_result = subprocess.run(
                            ["ps", "-p", str(pid), "-o", "command="],
                            capture_output=True,
                            text=True,
                            timeout=0.2,
                            check=False,
                        )
                        cmdline = cmdline_result.stdout.strip()
                        if "pool_runner" not in cmdline and "_pool_worker" not in cmdline:
                            return pid
                    except (ValueError, subprocess.TimeoutExpired):
                        continue

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
                ["lsof", "-i", f"TCP:{port}", "-t", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=0.3,  # 300ms timeout
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

        Only stops daemon via PID file - does NOT scan system processes.
        This prevents accidentally stopping Docker containerized daemons.

        Args:
            timeout: Maximum seconds to wait before SIGKILL escalation.

        Returns:
            True if a signal was sent and daemon stopped, False if no daemon found.
        """
        stopped = False
        pid: int | None = None

        # Only stop via PID file - don't scan system processes (avoids Docker conflicts)
        pf = pid_path()
        if pf.exists():
            try:
                pid = int(pf.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                stopped = SootheDaemon._wait_for_pid_exit(pid, timeout)
            except (ValueError, ProcessLookupError, PermissionError):
                pass

        # Cleanup PID file regardless of outcome
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
        logger.debug("Daemon did not stop within %.1f seconds, sending SIGKILL", timeout)
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
