"""StrangeLoop State Manager (RFC-205, RFC-216, IG-055).

Manages checkpoint lifecycle: initialize, save, load, recovery.
RFC-216: Multi-thread spanning with loop_id as primary key.
RFC-215: Unified global SQLite persistence backend (loop_checkpoints.db).
IG-055: PostgreSQL backend support using soothe_checkpoints database.
IG-258 Phase 2: Connection pooling to eliminate database lock contention.
IG-406: Shared pool for high-concurrency (200+ threads) support.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from soothe.config.constants import DEFAULT_STRANGE_LOOP_MAX_ITERATIONS
from soothe.sloop.checkpoints.directory_manager import (
    PersistenceDirectoryManager,
)
from soothe.sloop.checkpoints.sqlite_backend import (
    SQLitePersistenceBackend,
)
from soothe.sloop.state.checkpoint import (
    StrangeLoopCheckpoint,
    ThreadHealthMetrics,
    WorkingMemoryState,
)
from soothe.sloop.state.execution_checkpoint import GoalIndexEntry

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.sloop.checkpoints.shared_pool import SharedPostgreSQLPool
    from soothe.sloop.state.schemas import (
        AgentDecision,
        LoopState,
        PlanResult,
        StepExecutionRecord,
    )
    from soothe.sloop.state.working_memory import LoopWorkingMemory

logger = logging.getLogger(__name__)


def _is_async_loop_runtime_error(exc: BaseException) -> bool:
    """Return True when asyncio cannot run because the event loop is gone or mismatched."""
    if not isinstance(exc, RuntimeError):
        return False
    msg = str(exc).casefold()
    return (
        "no running event loop" in msg
        or "event loop is closed" in msg
        or "bound to a different event loop" in msg
    )


class StrangeLoopStateManager:
    """Manages StrangeLoop checkpoint lifecycle (RFC-216: loop-scoped, multi-thread).

    IG-055: Configuration-driven backend selection (PostgreSQL or SQLite).
    Uses PostgreSQL soothe_checkpoints database when configured, SQLite fallback.
    IG-258 Phase 2: Connection pooling for concurrent checkpoint operations.
    """

    def __init__(
        self,
        loop_id: str | None = None,
        reader_pool_size: int = 2,
        config: SootheConfig | None = None,
        shared_pool: SharedPostgreSQLPool | None = None,
    ) -> None:
        """Initialize with loop_id (primary key), not thread_id.

        Args:
            loop_id: Loop identifier (UUID or existing). None generates new UUID.
            reader_pool_size: Number of reader connections for concurrent reads (Phase 2).
            config: SootheConfig for backend selection (PostgreSQL vs SQLite).
            shared_pool: SharedPostgreSQLPool for high-concurrency (IG-406).
        """
        self.loop_id = loop_id or str(uuid.uuid4())
        self.run_dir = PersistenceDirectoryManager.get_loop_directory(
            self.loop_id
        )  # For reports/working_memory
        self._checkpoint: StrangeLoopCheckpoint | None = None

        # IG-055: Backend selection based on persistence.default_backend
        self._backend_type = "sqlite"  # Default
        self._postgres_backend = None
        self._postgres_dsn = None
        self._shared_pool = shared_pool  # IG-406: Shared pool reference

        if config and config.persistence.default_backend == "postgresql":
            self._backend_type = "postgresql"
            self._postgres_dsn = config.resolve_postgres_dsn_for_database("checkpoints")
            if shared_pool:
                logger.info(
                    "StrangeLoop using shared PostgreSQL pool: loop_id=%s",
                    self.loop_id,
                )
            else:
                logger.info(
                    "StrangeLoop using PostgreSQL backend (soothe_checkpoints database): loop_id=%s",
                    self.loop_id,
                )
        else:
            self.db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
            logger.info(
                "StrangeLoop using SQLite backend (loop_checkpoints.db): loop_id=%s",
                self.loop_id,
            )

        # Instance-level connection pool (Phase 2) - matching SQLitePersistStore pattern
        self._reader_pool_size = reader_pool_size
        self._writer_conn: sqlite3.Connection | None = None
        self._reader_pool: list[sqlite3.Connection] = []
        self._reader_pool_index = 0
        self._pool_semaphore = asyncio.Semaphore(reader_pool_size)
        self._init_lock = asyncio.Lock()

        # RFC-803 / IG-550: async coalesced checkpoint writes (always on).
        # Coerce to float: a non-numeric ``flush_interval`` (e.g. from an
        # incomplete mock config) would make ``asyncio.sleep`` raise TypeError
        # on every tick; the worker's broad ``except Exception`` would swallow
        # it with no sleep and busy-loop at ~100% CPU. Fall back to defaults.
        checkpoint_cfg = (
            config.agent.loop.concurrency.checkpoint
            if config and hasattr(config.agent.loop.concurrency, "checkpoint")
            else None
        )

        def _coerced(value: Any, default: float) -> float:
            try:
                coerced = float(value)
            except (TypeError, ValueError):
                return default
            return coerced if coerced > 0 else default

        self._flush_interval = _coerced(
            checkpoint_cfg.flush_interval if checkpoint_cfg else 5.0, 5.0
        )
        self._close_timeout_seconds = _coerced(
            checkpoint_cfg.close_timeout_seconds if checkpoint_cfg else 30.0, 30.0
        )
        self._durable_flush_timeout = _coerced(
            checkpoint_cfg.durable_flush_timeout if checkpoint_cfg else 10.0, 10.0
        )
        self._config = config
        self._loop_writer = None

        # SQLite-only async coalesce worker (PostgreSQL uses LoopPersistenceWriter)
        self._coalesced_pending: StrangeLoopCheckpoint | None = None
        self._flush_worker: asyncio.Task | None = None
        self._worker_loop: asyncio.AbstractEventLoop | None = None
        self._last_save_checkpoint: StrangeLoopCheckpoint | None = None
        self._worker_started = False
        self._worker_lock = asyncio.Lock()
        self._checkpoint_write_lock = asyncio.Lock()
        self._closed = False
        self._goal_boundary_persisted = False

    async def _ensure_loop_writer(self) -> Any | None:
        """Lazy-init process-scoped persistence writer (PostgreSQL only)."""
        if self._backend_type != "postgresql" or self._config is None:
            return None
        if self._loop_writer is not None:
            return self._loop_writer
        from soothe.persistence.loop_writer import LoopPersistenceWriter

        self._loop_writer = await LoopPersistenceWriter.get_shared_instance(
            self._config,
            shared_pool=self._shared_pool,
        )
        return self._loop_writer

    async def _ensure_backend_initialized(self) -> None:
        """Lazy backend initialization (IG-055: PostgreSQL or SQLite).

        IG-406: Uses shared pool when provided for high-concurrency support.
        Ensures appropriate backend is ready for operations.
        """
        if self._backend_type == "postgresql":
            if self._postgres_backend is None:
                # IG-406: Use shared pool if provided (high-concurrency mode)
                if self._shared_pool is not None:
                    from soothe.sloop.checkpoints.postgres_backend import (
                        PostgreSQLPersistenceBackend,
                    )

                    async with self._init_lock:
                        if self._postgres_backend is None:
                            # Create lightweight backend wrapper using shared pool
                            pool = self._shared_pool.get_pool()
                            if pool is not None:
                                self._postgres_backend = PostgreSQLPersistenceBackend(
                                    dsn=self._postgres_dsn,
                                    pool_size=0,  # pool_size=0: use provided pool
                                    shared_pool=self._shared_pool,  # For pool reset capability
                                )
                                self._postgres_backend._pool = pool  # Use shared pool directly
                                logger.info(
                                    "StrangeLoop PostgreSQL backend ready (shared pool): loop_id=%s",
                                    self.loop_id,
                                )
                else:
                    # IG-055: Create dedicated pool (single-threaded/low-concurrency mode)
                    from soothe.sloop.checkpoints.postgres_backend import (
                        PostgreSQLPersistenceBackend,
                    )

                    async with self._init_lock:
                        if self._postgres_backend is None:
                            self._postgres_backend = PostgreSQLPersistenceBackend(
                                dsn=self._postgres_dsn, pool_size=self._reader_pool_size
                            )
                            # Schema initialization happens in backend
                            logger.info(
                                "StrangeLoop PostgreSQL backend ready: loop_id=%s", self.loop_id
                            )
        else:
            # SQLite backend initialization
            if self._writer_conn is None:
                async with self._init_lock:
                    if self._writer_conn is None:
                        await asyncio.to_thread(self._init_writer_connection_sync)

    async def _ensure_writer_connection(self) -> sqlite3.Connection:
        """Lazy writer connection initialization with WAL mode (Phase 2).

        IG-055: SQLite-only, PostgreSQL uses connection pool.

        Returns:
            Active SQLite writer connection.
        """
        if self._backend_type == "postgresql":
            # PostgreSQL doesn't use direct writer connection
            raise RuntimeError("PostgreSQL backend doesn't use writer connection")

        await self._ensure_backend_initialized()
        return self._writer_conn

    def _init_writer_connection_sync(self) -> None:
        """Sync writer initialization executed in thread pool."""
        db_path = Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._writer_conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            timeout=30,
        )
        self._writer_conn.execute("PRAGMA journal_mode=WAL")
        self._writer_conn.execute("PRAGMA foreign_keys=ON")
        self._writer_conn.row_factory = sqlite3.Row

        # Initialize database schema
        SQLitePersistenceBackend.initialize_database_sync(db_path)

        logger.info("StrangeLoop SQLite writer connection initialized at %s", db_path)

    async def _get_reader_connection(self) -> sqlite3.Connection:
        """Get reader connection from pool (Phase 2).

        Uses semaphore to limit concurrent reads to pool size.
        Connections are leased round-robin and remain in the pool (no pop/leak).

        Returns:
            Reader connection from pool.
        """
        async with self._init_lock:
            if not self._reader_pool:
                await asyncio.to_thread(self._init_reader_pool_sync)

        async with self._pool_semaphore:
            index = self._reader_pool_index % len(self._reader_pool)
            self._reader_pool_index += 1
            return self._reader_pool[index]

    def _init_reader_pool_sync(self) -> None:
        """Sync reader pool initialization executed in thread pool."""
        db_path = Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        for _i in range(self._reader_pool_size):
            conn = sqlite3.connect(
                str(db_path),
                check_same_thread=False,
                timeout=30,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._reader_pool.append(conn)

        logger.info("StrangeLoop SQLite reader pool initialized: size=%d", self._reader_pool_size)

    async def _create_reader_conn(self) -> sqlite3.Connection:
        """Create new reader connection if pool empty."""
        return await asyncio.to_thread(self._create_reader_conn_sync)

    def _create_reader_conn_sync(self) -> sqlite3.Connection:
        """Sync reader connection creation."""
        db_path = Path(self.db_path)
        conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    async def initialize(
        self,
        thread_id: str,
        max_iterations: int = DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
    ) -> StrangeLoopCheckpoint:
        """Create new loop for thread (RFC-216: loop-scoped).

        IG-258 Phase 2: Database schema initialized lazily by writer connection.
        RFC-626 Phase 3: Initialize with schema_version 5.0 and execution_checkpoint.

        Args:
            thread_id: First thread for this loop
            max_iterations: Maximum loop iterations per goal

        Returns:
            New StrangeLoopCheckpoint instance (status=idle)
        """
        now = datetime.now(UTC)

        checkpoint = StrangeLoopCheckpoint(
            loop_id=self.loop_id,
            thread_ids=[thread_id],  # First thread
            current_thread_id=thread_id,
            status="idle",
            goal_history=[],
            current_goal_index=-1,  # No active goal yet
            working_memory_state=WorkingMemoryState(entries=[], spill_files=[]),
            thread_health_metrics=ThreadHealthMetrics(thread_id=thread_id, last_updated=now),
            total_goals_completed=0,
            total_thread_switches=0,
            total_duration_ms=0,
            total_tokens_used=0,
            created_at=now,
            updated_at=now,
            schema_version="5.0",  # RFC-626 Phase 3: execution_checkpoint pattern
            execution_checkpoint={
                "loop_id": self.loop_id,
                "thread_id": thread_id,
                "iteration": 0,
                "wave_metrics": {},
                "status": "idle",
            },
        )

        self._checkpoint = checkpoint
        await self._save_checkpoint_to_db(checkpoint)

        logger.info(
            "Initialized loop %s on thread %s (status: idle, schema: 5.0)",
            self.loop_id,
            thread_id,
        )

        return checkpoint

    def get_checkpoint(self) -> StrangeLoopCheckpoint | None:
        """Return the in-memory checkpoint without reloading from storage."""
        return self._checkpoint

    def _merge_loaded_checkpoint(self, loaded: StrangeLoopCheckpoint) -> StrangeLoopCheckpoint:
        """Prefer richer in-memory goal_history over stale index-only DB rows."""
        mem = self._checkpoint
        if mem is None:
            return loaded

        mem_goals = len(mem.goal_history)
        loaded_goals = len(loaded.goal_history)
        if mem_goals > loaded_goals:
            return loaded.model_copy(
                update={
                    "goal_history": list(mem.goal_history),
                    "current_goal_index": mem.current_goal_index,
                }
            )
        if (
            mem_goals == loaded_goals
            and mem_goals > 0
            and mem.updated_at
            and loaded.updated_at
            and mem.updated_at > loaded.updated_at
        ):
            return loaded.model_copy(
                update={
                    "goal_history": list(mem.goal_history),
                    "current_goal_index": mem.current_goal_index,
                }
            )
        return loaded

    def _resolve_goal_in_history(
        self,
        checkpoint: StrangeLoopCheckpoint,
        goal_record: GoalIndexEntry,
    ) -> GoalIndexEntry | None:
        """Find goal in history, repairing when index-only reload dropped entries."""
        for goal in checkpoint.goal_history:
            if goal.goal_id == goal_record.goal_id:
                return goal

        checkpoint.goal_history.append(goal_record)
        if checkpoint.current_goal_index < 0:
            checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
        logger.warning(
            "Repaired missing goal %s in goal_history (now %d entries)",
            goal_record.goal_id,
            len(checkpoint.goal_history),
        )
        return goal_record

    async def load(self) -> StrangeLoopCheckpoint | None:
        """Load existing loop checkpoint (RFC-216: by loop_id).

        IG-055: Backend-aware load (PostgreSQL or SQLite).
        IG-258 Phase 2: Use reader connection pool for concurrent reads (SQLite).

        Returns:
            StrangeLoopCheckpoint if exists and valid (v2.0 schema), None otherwise
        """
        # IG-055: PostgreSQL backend
        if self._backend_type == "postgresql":
            await self._ensure_backend_initialized()
            checkpoint = await self._postgres_backend.load_checkpoint(self.loop_id)

            if checkpoint:
                checkpoint = self._merge_loaded_checkpoint(checkpoint)
                self._checkpoint = checkpoint
                logger.debug(
                    "Loaded loop %s checkpoint from PostgreSQL (status %s, %d goals, %d threads)",
                    self.loop_id,
                    checkpoint.status,
                    len(checkpoint.goal_history),
                    len(checkpoint.thread_ids),
                )
            return checkpoint

        # SQLite backend (existing implementation)
        # Ensure backend is initialized before attempting load
        await self._ensure_backend_initialized()

        if not self.db_path.exists():
            return None

        try:
            # Get reader connection from pool (Phase 2)
            async with self._pool_semaphore:
                conn = await self._get_reader_connection()

                # Execute query in thread pool
                row_data = await asyncio.to_thread(
                    self._load_loop_metadata_sync, conn, self.loop_id
                )

                if not row_data:
                    return None

                # Deserialize row
                thread_ids = json.loads(row_data[0])
                current_thread_id = row_data[1]
                status = row_data[2]
                current_goal_index = row_data[3]
                working_memory_state = (
                    WorkingMemoryState.model_validate_json(row_data[4])
                    if row_data[4]
                    else WorkingMemoryState(entries=[], spill_files=[])
                )
                thread_health_metrics = (
                    ThreadHealthMetrics.model_validate_json(row_data[5])
                    if row_data[5]
                    else ThreadHealthMetrics(
                        thread_id=current_thread_id, last_updated=datetime.now(UTC)
                    )
                )
                total_goals_completed = row_data[6]
                total_thread_switches = row_data[7]
                total_duration_ms = row_data[8]
                total_tokens_used = row_data[9]
                thread_switch_pending = bool(row_data[10])
                created_at = datetime.fromisoformat(row_data[11])
                updated_at = datetime.fromisoformat(row_data[12])
                schema_version = row_data[13]

                # Load goal_history from goal_records table
                goal_rows_data = await asyncio.to_thread(
                    self._load_goal_records_sync, conn, self.loop_id
                )

                goal_history = []
                for goal_row in goal_rows_data:
                    goal_history.append(
                        GoalIndexEntry(
                            goal_id=goal_row[0],
                            thread_id=goal_row[2],
                            status=goal_row[3],
                            duration_ms=goal_row[4] or 0,
                            tokens_used=goal_row[5] or 0,
                            started_at=datetime.fromisoformat(goal_row[6]),
                            completed_at=datetime.fromisoformat(goal_row[7])
                            if goal_row[7]
                            else None,
                        )
                    )

                checkpoint = StrangeLoopCheckpoint(
                    loop_id=self.loop_id,
                    thread_ids=thread_ids,
                    current_thread_id=current_thread_id,
                    status=status,
                    goal_history=goal_history,
                    current_goal_index=current_goal_index,
                    working_memory_state=working_memory_state,
                    thread_health_metrics=thread_health_metrics,
                    total_goals_completed=total_goals_completed,
                    total_thread_switches=total_thread_switches,
                    total_duration_ms=total_duration_ms,
                    total_tokens_used=total_tokens_used,
                    thread_switch_pending=thread_switch_pending,
                    created_at=created_at,
                    updated_at=updated_at,
                    schema_version=schema_version,
                )

                checkpoint = self._merge_loaded_checkpoint(checkpoint)

                self._checkpoint = checkpoint

                # Auto-repair: Detect and fix orphaned running goals
                from soothe.sloop.state.status_vocabulary import (
                    is_goal_index_in_flight,
                    suggest_loop_checkpoint_status,
                )

                suggested_status = suggest_loop_checkpoint_status(
                    loop_status=checkpoint.status,
                    goal_index_statuses=[g.status for g in checkpoint.goal_history],
                )
                if checkpoint.status == "idle" and suggested_status == "running":
                    running_goals = [
                        g for g in checkpoint.goal_history if is_goal_index_in_flight(g.status)
                    ]
                    if running_goals:
                        logger.warning(
                            "Found orphaned in-flight goals in loop %s while loop status idle (%d goals)",
                            checkpoint.loop_id,
                            len(running_goals),
                        )
                        # Auto-repair: set index to last running goal
                        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
                        checkpoint.status = "running"
                        logger.info(
                            "Auto-repaired orphaned goal index: set to %d (goal_id=%s)",
                            checkpoint.current_goal_index,
                            checkpoint.goal_history[checkpoint.current_goal_index].goal_id,
                        )
                        # Save repaired checkpoint
                        await self._save_checkpoint_to_db(checkpoint)

                logger.info(
                    "Loaded loop %s checkpoint from SQLite (status %s, %d goals, %d threads)",
                    self.loop_id,
                    checkpoint.status,
                    len(checkpoint.goal_history),
                    len(checkpoint.thread_ids),
                )

                return checkpoint

        except Exception:
            logger.exception("Failed to load loop %s checkpoint", self.loop_id)
            return None

    def _load_loop_metadata_sync(self, conn: sqlite3.Connection, loop_id: str) -> tuple | None:
        """Sync load of loop metadata executed in thread pool."""
        cursor = conn.execute(
            """
            SELECT thread_ids, current_thread_id, status, current_goal_index,
                   working_memory_state, thread_health_metrics,
                   total_goals_completed, total_thread_switches,
                   total_duration_ms, total_tokens_used,
                   thread_switch_pending, created_at, updated_at, schema_version
            FROM agentloop_loops WHERE loop_id = ?
            """,
            (loop_id,),
        )
        return cursor.fetchone()

    def _load_goal_records_sync(self, conn: sqlite3.Connection, loop_id: str) -> list[tuple]:
        """Sync load of goal records executed in thread pool."""
        cursor = conn.execute(
            """
            SELECT goal_id, loop_id, thread_id, status,
                   duration_ms, tokens_used, started_at, completed_at
            FROM goal_records WHERE loop_id = ?
            ORDER BY started_at
            """,
            (loop_id,),
        )
        return cursor.fetchall()

    async def save(
        self,
        checkpoint: StrangeLoopCheckpoint,
        *,
        include_goal_history: bool = False,
    ) -> None:
        """Persist loop checkpoint to SQLite (RFC-216: indexed by loop_id).

        Args:
            checkpoint: Checkpoint to save
            include_goal_history: When True, write full checkpoint (goal_history
                included). Use on goal-start boundaries; default index-only is
                insufficient for reload merge.
        """
        await self._save_checkpoint_to_db(
            checkpoint,
            include_goal_history=include_goal_history,
        )

    async def _save_checkpoint_to_db(
        self,
        checkpoint: StrangeLoopCheckpoint,
        *,
        include_goal_history: bool = False,
    ) -> None:
        """Save checkpoint to database (IG-055: PostgreSQL or SQLite).

        IG-258 Phase 2: Use single writer connection for SQLite consistency.
        IG-055: PostgreSQL uses connection pool for async operations.
        RFC-803 Phase 6: Fire-and-forget async writes with periodic flush.
        """
        checkpoint.updated_at = datetime.now(UTC)

        # Immediate local cache update (ensures subsequent reads get latest)
        self._checkpoint = checkpoint
        self._last_save_checkpoint = checkpoint

        writer = await self._ensure_loop_writer()
        if writer is not None:
            from soothe.persistence.loop_writer import PersistWriteMode

            write_mode = (
                PersistWriteMode.FULL if include_goal_history else PersistWriteMode.INDEX_ONLY
            )
            await writer.submit_enqueue(
                self.loop_id,
                checkpoint,
                durable=False,
                write_mode=write_mode,
            )
            return

        if self._closed:
            await self._do_save_checkpoint(checkpoint)
            return

        if not self._worker_started:
            await self._start_flush_worker()

        self._coalesced_pending = checkpoint
        logger.debug(
            "Coalesced async checkpoint: loop=%s status=%s",
            self.loop_id,
            checkpoint.status,
        )

    async def _do_save_checkpoint(
        self,
        checkpoint: StrangeLoopCheckpoint,
        *,
        write_mode: str = "full",
    ) -> None:
        """Perform actual checkpoint write (called by worker or sync fallback).

        RFC-803 Phase 6: Extracted backend write logic for reuse.
        """
        async with self._checkpoint_write_lock:
            hot_cold = self._backend_type == "postgresql"
            if self._backend_type == "postgresql":
                await self._ensure_backend_initialized()
                await self._postgres_backend.save_checkpoint(
                    checkpoint,
                    write_mode=write_mode if hot_cold else "full",
                    hot_cold_enabled=hot_cold,
                )
            else:
                conn = await self._ensure_writer_connection()
                await asyncio.to_thread(self._save_checkpoint_sync, conn, checkpoint)

    async def _start_flush_worker(self) -> None:
        """Start SQLite background worker for periodic coalesced flushes."""
        async with self._worker_lock:
            if self._closed or self._worker_started:
                return

            worker_loop = asyncio.get_running_loop()
            self._worker_loop = worker_loop
            self._flush_worker = worker_loop.create_task(self._flush_worker_loop())
            self._worker_started = True

            logger.info(
                "Async checkpoint worker started: loop=%s flush_interval=%ss",
                self.loop_id,
                self._flush_interval,
            )

    async def _stop_flush_worker(self, *, timeout: float | None = None) -> None:
        """Stop the SQLite flush worker and drain coalesced pending writes."""
        timeout = self._close_timeout_seconds if timeout is None else timeout
        async with self._worker_lock:
            coalesced = self._coalesced_pending
            self._coalesced_pending = None
            worker = self._flush_worker
            self._flush_worker = None
            self._worker_started = False
            self._worker_loop = None

        async def _drain() -> None:
            if coalesced is not None:
                await self._do_save_checkpoint(coalesced, write_mode="full")

        try:
            async with asyncio.timeout(timeout):
                await _drain()
        except TimeoutError:
            logger.warning(
                "Checkpoint worker drain timed out after %.0fs loop=%s",
                timeout,
                self.loop_id,
            )

        if worker is None:
            return

        worker.cancel()
        try:
            async with asyncio.timeout(timeout):
                await worker
        except (TimeoutError, asyncio.CancelledError):
            pass

    async def _flush_worker_loop(self) -> None:
        """Periodic flush of coalesced SQLite checkpoint writes."""
        while True:
            try:
                await asyncio.sleep(self._flush_interval)
                if self._coalesced_pending is not None:
                    pending = self._coalesced_pending
                    self._coalesced_pending = None
                    await self._do_save_checkpoint(pending, write_mode="full")
            except asyncio.CancelledError:
                logger.info("Async checkpoint worker stopped: loop=%s", self.loop_id)
                raise
            except RuntimeError as exc:
                if _is_async_loop_runtime_error(exc):
                    logger.warning(
                        "Async checkpoint worker stopping: event loop unavailable loop=%s",
                        self.loop_id,
                    )
                    return
                raise
            except Exception:
                logger.exception("Async checkpoint write failed: loop=%s", self.loop_id)

    async def force_flush(self, *, timeout: float | None = None) -> None:
        """Force immediate checkpoint write (for critical operations).

        RFC-803 Phase 6: Used by finalize_loop, archive_and_finalize, close.
        """
        timeout = self._durable_flush_timeout if timeout is None else timeout
        if not self._last_save_checkpoint:
            return

        writer = await self._ensure_loop_writer()
        if writer is not None:
            result = await writer.submit_flush_durable(self.loop_id, timeout=timeout)
            if not result.ok:
                from soothe.persistence.checkpoint_split import mark_persist_degraded

                mark_persist_degraded(self._last_save_checkpoint)
            else:
                self._goal_boundary_persisted = True
            logger.info("Force checkpoint flush: loop=%s ok=%s", self.loop_id, result.ok)
            return

        async def _flush() -> None:
            if self._coalesced_pending is not None:
                pending = self._coalesced_pending
                self._coalesced_pending = None
                await self._do_save_checkpoint(pending, write_mode="full")
            await self._do_save_checkpoint(self._last_save_checkpoint, write_mode="full")

        try:
            async with asyncio.timeout(timeout):
                await _flush()
            self._goal_boundary_persisted = True
            logger.info("Force checkpoint flush: loop=%s", self.loop_id)
        except TimeoutError:
            logger.warning(
                "Force checkpoint flush timed out after %.0fs loop=%s",
                timeout,
                self.loop_id,
            )
            from soothe.persistence.checkpoint_split import mark_persist_degraded

            mark_persist_degraded(self._last_save_checkpoint)

    def _save_checkpoint_sync(
        self, conn: sqlite3.Connection, checkpoint: StrangeLoopCheckpoint
    ) -> None:
        """Sync save of checkpoint executed in thread pool.

        Bug 5.3 fix: Uses UPDATE (not INSERT OR REPLACE) for agentloop_loops.
        Preserves daemon-managed lifecycle statuses (detached, paused, archived)
        via CASE WHEN — if the daemon changed status between subprocess load
        and save, the subprocess preserves it instead of clobbering.
        Also preserves daemon-managed fields: client_workspace, detached_at,
        created_at, schema_version.

        RFC-626 Phase 3: Includes execution_checkpoint field for schema 5.0.
        """
        # Serialize complex structures to JSON strings
        thread_ids_json = json.dumps(checkpoint.thread_ids, ensure_ascii=False)
        working_memory_json = checkpoint.working_memory_state.model_dump_json()
        thread_health_json = checkpoint.thread_health_metrics.model_dump_json()
        # RFC-626 Phase 3: Serialize execution_checkpoint
        execution_checkpoint_json = (
            json.dumps(checkpoint.execution_checkpoint, ensure_ascii=False)
            if checkpoint.execution_checkpoint
            else None
        )

        # UPDATE agentloop_loops — preserves daemon-managed fields and statuses
        conn.execute(
            """
            UPDATE agentloop_loops
            SET thread_ids = ?,
                current_thread_id = ?,
                status = CASE
                    WHEN status IN ('detached', 'paused', 'archived') THEN status
                    ELSE ?
                END,
                current_goal_index = ?,
                working_memory_state = ?,
                thread_health_metrics = ?,
                total_goals_completed = ?,
                total_thread_switches = ?,
                total_duration_ms = ?,
                total_tokens_used = ?,
                thread_switch_pending = ?,
                updated_at = ?,
                execution_checkpoint = ?
            WHERE loop_id = ?
            """,
            (
                thread_ids_json,
                checkpoint.current_thread_id,
                checkpoint.status,
                checkpoint.current_goal_index,
                working_memory_json,
                thread_health_json,
                checkpoint.total_goals_completed,
                checkpoint.total_thread_switches,
                checkpoint.total_duration_ms,
                checkpoint.total_tokens_used,
                int(checkpoint.thread_switch_pending),
                checkpoint.updated_at.isoformat(),
                execution_checkpoint_json,
                checkpoint.loop_id,
            ),
        )

        # If no rows were updated (loop not yet registered), fall back to INSERT.
        # This can happen if initialize() runs before the daemon's register_loop.
        rows_affected = conn.execute("SELECT changes()").fetchone()[0]
        if rows_affected == 0:
            conn.execute(
                """
                INSERT OR IGNORE INTO agentloop_loops
                (loop_id, thread_ids, current_thread_id, status, current_goal_index,
                 working_memory_state, thread_health_metrics,
                 total_goals_completed, total_thread_switches,
                 total_duration_ms, total_tokens_used, thread_switch_pending,
                 created_at, updated_at, schema_version, execution_checkpoint)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.loop_id,
                    thread_ids_json,
                    checkpoint.current_thread_id,
                    checkpoint.status,
                    checkpoint.current_goal_index,
                    working_memory_json,
                    thread_health_json,
                    checkpoint.total_goals_completed,
                    checkpoint.total_thread_switches,
                    checkpoint.total_duration_ms,
                    checkpoint.total_tokens_used,
                    int(checkpoint.thread_switch_pending),
                    checkpoint.created_at.isoformat(),
                    checkpoint.updated_at.isoformat(),
                    checkpoint.schema_version,
                    execution_checkpoint_json,
                ),
            )

        # Save goal_history to goal_records table
        for goal_record in checkpoint.goal_history:
            logger.debug(
                "save goal: id=%s status=%s done=%s",
                goal_record.goal_id,
                goal_record.status,
                goal_record.completed_at.isoformat() if goal_record.completed_at else "None",
            )

            completed_at_str = (
                goal_record.completed_at.isoformat() if goal_record.completed_at else None
            )

            conn.execute(
                """
                INSERT OR REPLACE INTO goal_records
                (goal_id, loop_id, thread_id, status,
                 duration_ms, tokens_used, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    goal_record.goal_id,
                    checkpoint.loop_id,
                    goal_record.thread_id,
                    goal_record.status,
                    goal_record.duration_ms,
                    goal_record.tokens_used,
                    goal_record.started_at.isoformat(),
                    completed_at_str,
                ),
            )

        conn.commit()

    def start_new_goal(
        self,
        goal: str,
        max_iterations: int = DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
    ) -> GoalIndexEntry:
        """Create new goal index entry and clear working memory (RFC-216).

        Args:
            goal: Goal description (stored in CE, not checkpoint index)
            max_iterations: Maximum iterations for this goal (execution config)

        Returns:
            New GoalIndexEntry (thread_id = current_thread_id)

        Raises:
            ValueError: If checkpoint is None or loop status is 'running'
        """
        if self._checkpoint is None:
            raise ValueError("No checkpoint to add goal to")

        checkpoint = self._checkpoint

        # Validate: Cannot start new goal while loop is already running
        if checkpoint.status == "running":
            raise ValueError(
                f"Cannot start new goal while loop is running (status={checkpoint.status}, "
                f"current_goal_index={checkpoint.current_goal_index})"
            )

        # Generate goal_id (loop-scoped sequence, independent of thread)
        goal_id = f"{checkpoint.loop_id}_goal_{len(checkpoint.goal_history)}"

        now = datetime.now(UTC)

        _ = goal, max_iterations
        goal_record = GoalIndexEntry(
            goal_id=goal_id,
            thread_id=checkpoint.current_thread_id,
            status="running",
            duration_ms=0,
            tokens_used=0,
            started_at=now,
            completed_at=None,
        )

        # Clear working memory for new goal
        checkpoint.working_memory_state = WorkingMemoryState(entries=[], spill_files=[])

        return goal_record

    def _apply_goal_finalize_memory(self, goal_record: GoalIndexEntry) -> None:
        """Update in-memory checkpoint for a completed goal (no persist)."""
        if self._checkpoint is None:
            return

        checkpoint = self._checkpoint
        target_goal = self._resolve_goal_in_history(checkpoint, goal_record)
        if target_goal is None:
            return

        logger.debug(
            "finalize_goal: found id=%s same_obj=%s",
            target_goal.goal_id,
            target_goal is goal_record,
        )

        target_goal.status = "completed"
        target_goal.completed_at = datetime.now(UTC)

        logger.debug(
            "finalize_goal: modified id=%s status=%s",
            target_goal.goal_id,
            target_goal.status,
        )

        checkpoint.total_goals_completed += 1
        checkpoint.total_duration_ms += target_goal.duration_ms
        checkpoint.total_tokens_used += target_goal.tokens_used
        checkpoint.thread_health_metrics.consecutive_goal_failures = 0
        checkpoint.thread_health_metrics.consecutive_rate_limit_errors = 0
        checkpoint.thread_health_metrics.last_goal_status = "completed"
        checkpoint.status = "idle"
        checkpoint.current_goal_index = -1

    async def persist_goal_boundary_durable(
        self,
        *,
        dag: Any | None = None,
        ledger: list[Any] | None = None,
    ) -> Any:
        """Durable goal-boundary persist (checkpoint + optional CE) in one transaction."""
        from soothe.persistence.loop_writer import PersistResult

        if self._checkpoint is None:
            return PersistResult(ok=True)

        writer = await self._ensure_loop_writer()
        if writer is None:
            await self.force_flush(timeout=self._durable_flush_timeout)
            self._goal_boundary_persisted = True
            return PersistResult(ok=True)

        result = await writer.submit_persist_goal_boundary(
            self.loop_id,
            checkpoint=self._checkpoint,
            dag=dag,
            ledger=ledger,
        )
        self._goal_boundary_persisted = result.ok
        return result

    async def finalize_goal(
        self,
        goal_record: GoalIndexEntry,
        *,
        skip_persist: bool = False,
    ) -> None:
        """Mark goal completed, update loop metrics.

        Args:
            goal_record: Goal execution record to finalize.
            skip_persist: When True, only apply in-memory updates (tail uses durable persist).
        """
        self._apply_goal_finalize_memory(goal_record)
        if skip_persist:
            logger.info(
                "Finalized goal %s in memory (persist deferred) loop=%s",
                goal_record.goal_id,
                self.loop_id,
            )
            return

        if self._checkpoint is None:
            return

        await self.save(self._checkpoint)
        await self.force_flush(timeout=self._durable_flush_timeout)

        logger.info(
            "Finalized goal %s on thread %s (loop %s)",
            goal_record.goal_id,
            goal_record.thread_id,
            self.loop_id,
        )

    async def record_iteration(
        self,
        goal_record: GoalIndexEntry,
        iteration: int,
        plan_result: PlanResult,
        decision: AgentDecision | None,  # Allow None for immediate completion
        step_results: list[StepExecutionRecord],
        state: LoopState,
        working_memory: LoopWorkingMemory | None,
    ) -> None:
        """Update goal record after each iteration (RFC-216, RFC-214).

        RFC-214: Ledger already contains Plan and Execute turns.
        This method only updates metrics and working memory.

        Args:
            goal_record: Goal execution record to update
            iteration: Current iteration number
            plan_result: Plan phase result
            decision: AgentDecision that was executed (or None for immediate completion)
            step_results: Step execution results
            state: LoopState with metrics and ledger
            working_memory: Current working memory state (optional)
        """
        if self._checkpoint is None:
            logger.error("No checkpoint to update")
            return

        checkpoint = self._checkpoint

        # BUGFIX: Modify goal_history entry directly (not passed parameter)
        # Pydantic model_copy() creates new instances, so goal_record may be detached
        target_goal = self._resolve_goal_in_history(checkpoint, goal_record)
        if target_goal is None:
            return

        logger.debug(
            "record_iteration: found id=%s same_obj=%s",
            target_goal.goal_id,
            target_goal is goal_record,
        )

        # RFC-624 Phase 4 Stage 2: No loop_messages deep-copy.
        # CE LedgerManager spans all goals, persisted via ce.save().
        # CE ledger spans all goals; no checkpoint mirroring.

        # Record working memory state
        if working_memory is not None:
            checkpoint.working_memory_state = self._serialize_working_memory(working_memory)

        # Update goal metrics (iteration tracked in execution_checkpoint)
        target_goal.duration_ms += sum(r.duration_ms for r in step_results)
        target_goal.tokens_used = state.total_tokens_used
        exec_cp = dict(checkpoint.execution_checkpoint or {})
        exec_cp["iteration"] = iteration + 1
        exec_cp.setdefault("loop_id", checkpoint.loop_id)
        exec_cp.setdefault("thread_id", checkpoint.current_thread_id)
        checkpoint.execution_checkpoint = exec_cp

        logger.debug(
            "record_iteration: updated iter=%d dur=%dms tok=%d",
            iteration + 1,
            target_goal.duration_ms,
            target_goal.tokens_used,
        )

        # Save checkpoint
        await self.save(checkpoint)

    async def finalize_loop(self, status: str) -> None:
        """Mark loop finalized (no more goals accepted).

        RFC-803 Phase 6: Uses force_flush for critical final state persistence.

        Args:
            status: Final status (finalized, cancelled)
        """
        if self._checkpoint is None:
            return

        self._checkpoint.status = status
        # Use force_flush for critical operations - must persist final state
        await self.force_flush()

        logger.info("Finalized loop %s (status: %s)", self.loop_id, status)

    async def archive_and_finalize(
        self,
        *,
        reason: Literal["user_clear", "finalized", "expired"] = "user_clear",
    ) -> dict[str, Any]:
        """Archive loop checkpoint and mark as finalized (IG-500).

        Saves checkpoint to archive storage, preserving goal_history and metrics.
        Used by /clear command to preserve loop history before creating fresh loop.

        Args:
            reason: Archival trigger reason.

        Returns:
            Archive metadata dict for broadcast and knowledge transfer.
        """
        from soothe.sloop.checkpoints.archive_backend import ArchiveBackend

        if self._checkpoint is None:
            raise ValueError("No active checkpoint to archive")

        # Mark as finalized
        self._checkpoint.status = "finalized"
        self._checkpoint.updated_at = datetime.now(UTC)

        # Archive via backend
        archive_backend = ArchiveBackend()
        archive_path = await archive_backend.archive_loop(
            self._checkpoint,
            reason=reason,
        )

        # Generate metadata
        metadata = {
            "loop_id": self.loop_id,
            "archived_at": datetime.now(UTC).isoformat(),
            "reason": reason,
            "goal_count": len(self._checkpoint.goal_history),
            "goals_completed": sum(
                1 for g in self._checkpoint.goal_history if g.status == "completed"
            ),
            "total_tokens_used": self._checkpoint.total_tokens_used,
            "total_duration_ms": self._checkpoint.total_duration_ms,
            "archive_path": archive_path,
        }

        # RFC-803 Phase 6: Force flush for critical archive operation
        await self.force_flush()

        logger.info(
            "Archived loop %s: goals=%d completed=%d reason=%s path=%s",
            self.loop_id,
            metadata["goal_count"],
            metadata["goals_completed"],
            reason,
            archive_path,
        )

        return metadata

    async def reinitialize_for_clear(
        self,
        old_thread_id: str,
    ) -> tuple[str, StrangeLoopCheckpoint]:
        """Create fresh loop after /clear (IG-500).

        Generates new loop_id with fresh state (empty goal_history, reset metrics).
        Thread_id reused for immediate continuation. Workspace metadata from the
        prior loop is copied so mounted client workspaces survive the clear.

        Args:
            old_thread_id: Thread to reuse for new loop.

        Returns:
            Tuple of (new_loop_id, new_checkpoint).
        """
        old_loop_id = self.loop_id
        inherited_metadata = await self._load_daemon_loop_metadata(old_loop_id)

        # Generate new loop_id
        new_loop_id = str(uuid.uuid4())

        # Update self.loop_id to new value
        self.loop_id = new_loop_id

        # Update run_dir for new loop
        self.run_dir = PersistenceDirectoryManager.get_loop_directory(new_loop_id)

        # Create fresh checkpoint
        now = datetime.now(UTC)
        new_checkpoint = StrangeLoopCheckpoint(
            loop_id=new_loop_id,
            thread_ids=[old_thread_id],  # Reuse thread for immediate continuation
            current_thread_id=old_thread_id,
            status="idle",
            goal_history=[],  # Empty
            current_goal_index=-1,
            working_memory_state=WorkingMemoryState(entries=[], spill_files=[]),
            thread_health_metrics=ThreadHealthMetrics(
                thread_id=old_thread_id,
                last_updated=now,
            ),
            total_goals_completed=0,
            total_thread_switches=0,
            total_duration_ms=0,
            total_tokens_used=0,
            created_at=now,
            updated_at=now,
            schema_version="5.0",
            execution_checkpoint={
                "loop_id": new_loop_id,
                "thread_id": old_thread_id,
                "iteration": 0,
                "wave_metrics": {},
                "status": "idle",
            },
        )

        # Update self
        self._checkpoint = new_checkpoint

        # Persist new checkpoint
        await self._save_checkpoint_to_db(new_checkpoint)
        await self._apply_daemon_loop_metadata(new_loop_id, inherited_metadata)

        logger.info(
            "Reinitialized loop after clear: new_loop_id=%s thread=%s inherited_workspace=%s",
            new_loop_id,
            old_thread_id,
            bool(inherited_metadata.get("current_workspace")),
        )

        return new_loop_id, new_checkpoint

    async def _load_daemon_loop_metadata(self, loop_id: str) -> dict[str, Any]:
        """Load daemon-owned workspace metadata for a loop."""
        from soothe.sloop.checkpoints.daemon_loop_metadata import (
            extract_daemon_loop_metadata,
        )

        if self._backend_type == "postgresql":
            await self._ensure_backend_initialized()
            if self._postgres_backend is None:
                return {}
            meta = await self._postgres_backend.get_loop_metadata(loop_id)
            return extract_daemon_loop_metadata(meta)

        backend = SQLitePersistenceBackend(Path(self.db_path))
        meta = await backend.get_loop_metadata(loop_id)
        return extract_daemon_loop_metadata(meta)

    async def _apply_daemon_loop_metadata(
        self,
        loop_id: str,
        metadata: dict[str, Any],
    ) -> None:
        """Persist daemon workspace metadata onto a loop row."""
        if not metadata:
            return

        if self._backend_type == "postgresql":
            await self._ensure_backend_initialized()
            if self._postgres_backend is None:
                return
            await self._postgres_backend.update_loop_metadata(loop_id, **metadata)
            return

        backend = SQLitePersistenceBackend(Path(self.db_path))
        await backend.update_loop_metadata(loop_id, **metadata)

    async def close(self) -> None:
        """Close backend connection pools (IG-404, IG-406).

        IG-404: Prevent pool exhaustion in concurrent execution.
        IG-406: Shared pools are closed at daemon level, not per-StrangeLoop.
        RFC-803 Phase 6: Force final checkpoint flush before closing.

        Must be called after StrangeLoop completes to release database connections.
        For shared pool mode, only clears references (pool closed at daemon shutdown).
        """
        self._closed = True
        try:
            async with asyncio.timeout(self._close_timeout_seconds):
                writer = await self._ensure_loop_writer()
                if writer is not None:
                    if not self._goal_boundary_persisted and self._last_save_checkpoint:
                        from soothe.persistence.loop_writer import PersistWriteMode

                        await writer.submit_enqueue(
                            self.loop_id,
                            self._last_save_checkpoint,
                            durable=True,
                            write_mode=PersistWriteMode.FULL,
                        )
                    await writer.submit_release_loop(
                        self.loop_id,
                        timeout=self._close_timeout_seconds,
                    )
                else:
                    await self._stop_flush_worker(timeout=self._close_timeout_seconds)
                    if not self._goal_boundary_persisted:
                        await self.force_flush(timeout=self._close_timeout_seconds)
        except TimeoutError:
            logger.warning(
                "StrangeLoopStateManager.close timed out after %.0fs loop=%s",
                self._close_timeout_seconds,
                self.loop_id,
            )
            if self._checkpoint is not None:
                from soothe.persistence.checkpoint_split import mark_persist_degraded

                mark_persist_degraded(self._checkpoint)

        # Close PostgreSQL backend pool (only if owned, not shared)
        if self._postgres_backend is not None:
            await self._postgres_backend.close()
            self._postgres_backend = None
            # IG-406: Clear shared pool reference but don't close it
            self._shared_pool = None
            logger.debug("Released PostgreSQL backend for loop %s", self.loop_id)

        # Close SQLite connections (always owned by this manager)
        if self._writer_conn is not None:
            await asyncio.to_thread(self._close_writer_sync)
            logger.debug("Closed SQLite writer connection for loop %s", self.loop_id)

        # Close reader pool connections
        if self._reader_pool:
            await asyncio.to_thread(self._close_reader_pool_sync)
            logger.debug("Closed SQLite reader pool for loop %s", self.loop_id)

    def _close_writer_sync(self) -> None:
        """Sync close of writer connection."""
        if self._writer_conn:
            self._writer_conn.close()
            self._writer_conn = None

    def _close_reader_pool_sync(self) -> None:
        """Sync close of reader pool connections."""
        for conn in self._reader_pool:
            conn.close()
        self._reader_pool.clear()

    def _serialize_working_memory(self, working_memory: LoopWorkingMemory) -> WorkingMemoryState:
        """Serialize working memory state."""
        spill_files = []
        lines = working_memory._lines if hasattr(working_memory, "_lines") else []

        for line in lines:
            if "— full output in" in line and ".md`" in line:
                import re

                match = re.search(r"`([^`]+\.md)`", line)
                if match:
                    spill_files.append(match.group(1))

        return WorkingMemoryState(
            entries=[],  # Entries reconstructed from step results
            spill_files=spill_files,
        )
