"""AgentLoop State Manager (RFC-205, RFC-216, IG-055).

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
from typing import TYPE_CHECKING

from soothe.core.loop.state.checkpoint import (
    AgentLoopCheckpoint,
    GoalExecutionRecord,
    ThreadHealthMetrics,
    WorkingMemoryState,
)
from soothe.core.loop.state.persistence.directory_manager import (
    PersistenceDirectoryManager,
)
from soothe.core.loop.state.persistence.sqlite_backend import (
    SQLitePersistenceBackend,
)
from soothe.core.loop.state.schemas import EvidenceEntry, PlanResult, StepResult
from soothe.core.loop.utils.messages import LoopAIMessage, LoopHumanMessage

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.core.loop.state.persistence.shared_pool import SharedPostgreSQLPool
    from soothe.core.loop.state.schemas import (
        AgentDecision,
        LoopState,
    )
    from soothe.core.loop.state.working_memory import LoopWorkingMemory

logger = logging.getLogger(__name__)


class AgentLoopStateManager:
    """Manages AgentLoop checkpoint lifecycle (RFC-216: loop-scoped, multi-thread).

    IG-055: Configuration-driven backend selection (PostgreSQL or SQLite).
    Uses PostgreSQL soothe_checkpoints database when configured, SQLite fallback.
    IG-258 Phase 2: Connection pooling for concurrent checkpoint operations.
    """

    def __init__(
        self,
        loop_id: str | None = None,
        workspace: Path | None = None,
        reader_pool_size: int = 5,
        config: SootheConfig | None = None,
        shared_pool: SharedPostgreSQLPool | None = None,
    ) -> None:  # noqa: ARG002
        """Initialize with loop_id (primary key), not thread_id.

        IG-055: Configuration-driven backend selection.
        IG-258 Phase 2: Instance-level connection pool.
        IG-406: Shared pool for high-concurrency support.

        Args:
            loop_id: Loop identifier (UUID or existing). None generates new UUID.
            workspace: Optional workspace path (not used for checkpoint storage)
            reader_pool_size: Number of reader connections for concurrent reads (Phase 2).
            config: SootheConfig for backend selection (PostgreSQL vs SQLite).
            shared_pool: SharedPostgreSQLPool for high-concurrency (IG-406).
        """
        self.loop_id = loop_id or str(uuid.uuid4())
        self.run_dir = PersistenceDirectoryManager.get_loop_directory(
            self.loop_id
        )  # For reports/working_memory
        self._checkpoint: AgentLoopCheckpoint | None = None

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
                    "AgentLoop using shared PostgreSQL pool: loop_id=%s",
                    self.loop_id,
                )
            else:
                logger.info(
                    "AgentLoop using PostgreSQL backend (soothe_checkpoints database): loop_id=%s",
                    self.loop_id,
                )
        else:
            self.db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
            logger.info(
                "AgentLoop using SQLite backend (loop_checkpoints.db): loop_id=%s",
                self.loop_id,
            )

        # Instance-level connection pool (Phase 2) - matching SQLitePersistStore pattern
        self._reader_pool_size = reader_pool_size
        self._writer_conn: sqlite3.Connection | None = None
        self._reader_pool: list[sqlite3.Connection] = []
        self._pool_semaphore = asyncio.Semaphore(reader_pool_size)
        self._init_lock = asyncio.Lock()

    async def _ensure_backend_initialized(self) -> None:
        """Lazy backend initialization (IG-055: PostgreSQL or SQLite).

        IG-406: Uses shared pool when provided for high-concurrency support.
        Ensures appropriate backend is ready for operations.
        """
        if self._backend_type == "postgresql":
            if self._postgres_backend is None:
                # IG-406: Use shared pool if provided (high-concurrency mode)
                if self._shared_pool is not None:
                    from soothe.core.loop.state.persistence.postgres_backend import (
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
                                )
                                self._postgres_backend._pool = pool  # Use shared pool directly
                                logger.info(
                                    "AgentLoop PostgreSQL backend ready (shared pool): loop_id=%s",
                                    self.loop_id,
                                )
                else:
                    # IG-055: Create dedicated pool (single-threaded/low-concurrency mode)
                    from soothe.core.loop.state.persistence.postgres_backend import (
                        PostgreSQLPersistenceBackend,
                    )

                    async with self._init_lock:
                        if self._postgres_backend is None:
                            self._postgres_backend = PostgreSQLPersistenceBackend(
                                dsn=self._postgres_dsn, pool_size=self._reader_pool_size
                            )
                            # Schema initialization happens in backend
                            logger.info(
                                "AgentLoop PostgreSQL backend ready: loop_id=%s", self.loop_id
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

        logger.info("AgentLoop SQLite writer connection initialized at %s", db_path)

    async def _get_reader_connection(self) -> sqlite3.Connection:
        """Get reader connection from pool (Phase 2).

        Uses semaphore to limit concurrent reads to pool size.

        Returns:
            Reader connection from pool.
        """
        async with self._init_lock:
            if not self._reader_pool:
                # Initialize reader pool
                await asyncio.to_thread(self._init_reader_pool_sync)

            # Return connection from pool (or create new if pool empty)
            return (
                self._reader_pool.pop() if self._reader_pool else await self._create_reader_conn()
            )

    def _init_reader_pool_sync(self) -> None:
        """Sync reader pool initialization executed in thread pool."""
        db_path = Path(self.db_path)
        for i in range(self._reader_pool_size):
            conn = sqlite3.connect(
                str(db_path),
                check_same_thread=False,
                timeout=30,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._reader_pool.append(conn)

        logger.info("AgentLoop SQLite reader pool initialized: size=%d", self._reader_pool_size)

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

    async def initialize(self, thread_id: str, max_iterations: int = 10) -> AgentLoopCheckpoint:
        """Create new loop for thread (RFC-216: loop-scoped).

        IG-258 Phase 2: Database schema initialized lazily by writer connection.

        Args:
            thread_id: First thread for this loop
            max_iterations: Maximum loop iterations per goal

        Returns:
            New AgentLoopCheckpoint instance (status=idle)
        """
        now = datetime.now(UTC)

        checkpoint = AgentLoopCheckpoint(
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
            schema_version="3.2",  # RFC-225 enrichment
        )

        self._checkpoint = checkpoint
        await self._save_checkpoint_to_db(checkpoint)

        logger.info(
            "Initialized loop %s on thread %s (status: idle)",
            self.loop_id,
            thread_id,
        )

        return checkpoint

    async def load(self) -> AgentLoopCheckpoint | None:
        """Load existing loop checkpoint (RFC-216: by loop_id).

        IG-055: Backend-aware load (PostgreSQL or SQLite).
        IG-258 Phase 2: Use reader connection pool for concurrent reads (SQLite).

        Returns:
            AgentLoopCheckpoint if exists and valid (v2.0 schema), None otherwise
        """
        # IG-055: PostgreSQL backend
        if self._backend_type == "postgresql":
            await self._ensure_backend_initialized()
            checkpoint = await self._postgres_backend.load_checkpoint(self.loop_id)

            if checkpoint:
                self._checkpoint = checkpoint
                logger.info(
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
                    # Deserialize loop_messages (RFC-214: replaces reason_history/act_history)
                    loop_messages_raw = json.loads(goal_row[6]) if goal_row[6] else []
                    loop_messages = [
                        LoopHumanMessage.model_validate(msg)
                        if msg.get("type") == "human"
                        else LoopAIMessage.model_validate(msg)
                        for msg in loop_messages_raw
                    ]

                    # RFC-225: unpack enriched fields stored in extras_jsonb
                    extras_raw = goal_row[13] if len(goal_row) > 13 else None
                    extras = json.loads(extras_raw) if extras_raw else {}

                    goal_record = GoalExecutionRecord(
                        goal_id=goal_row[0],
                        goal_text=goal_row[2],
                        thread_id=goal_row[3],
                        iteration=goal_row[4],
                        max_iterations=extras.get("max_iterations", 10),
                        status=goal_row[5],
                        loop_messages=loop_messages,  # RFC-214: ledger
                        goal_completion=goal_row[7] or "",
                        evidence_summary=goal_row[8] or "",
                        duration_ms=goal_row[9],
                        tokens_used=goal_row[10],
                        started_at=datetime.fromisoformat(goal_row[11]),
                        completed_at=datetime.fromisoformat(goal_row[12]) if goal_row[12] else None,
                        # RFC-225 enrichment (default to empty on legacy rows)
                        current_plan=(
                            PlanResult.model_validate(extras["current_plan"])
                            if extras.get("current_plan")
                            else None
                        ),
                        completed_step_ids=set(extras.get("completed_step_ids", [])),
                        plan_revision_count=extras.get("plan_revision_count", 0),
                        step_results=[
                            StepResult.model_validate(s) for s in extras.get("step_results", [])
                        ],
                        evidence_ledger=[
                            EvidenceEntry.model_validate(e)
                            for e in extras.get("evidence_ledger", [])
                        ],
                    )
                    goal_history.append(goal_record)

                checkpoint = AgentLoopCheckpoint(
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

                self._checkpoint = checkpoint

                # Auto-repair: Detect and fix orphaned running goals
                if checkpoint.status == "idle" and checkpoint.current_goal_index == -1:
                    # Check if goal_history has running goals
                    running_goals = [g for g in checkpoint.goal_history if g.status == "running"]
                    if running_goals:
                        logger.warning(
                            "Found orphaned running goals in loop %s (index=-1 but %d running goals)",
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
            SELECT goal_id, loop_id, goal_text, thread_id, iteration, status,
                   loop_messages, goal_completion, evidence_summary,
                   duration_ms, tokens_used, started_at, completed_at,
                   extras_jsonb
            FROM goal_records WHERE loop_id = ?
            ORDER BY started_at
            """,
            (loop_id,),
        )
        return cursor.fetchall()

    async def save(self, checkpoint: AgentLoopCheckpoint) -> None:
        """Persist loop checkpoint to SQLite (RFC-216: indexed by loop_id).

        Args:
            checkpoint: Checkpoint to save
        """
        await self._save_checkpoint_to_db(checkpoint)

    async def _save_checkpoint_to_db(self, checkpoint: AgentLoopCheckpoint) -> None:
        """Save checkpoint to database (IG-055: PostgreSQL or SQLite).

        IG-258 Phase 2: Use single writer connection for SQLite consistency.
        IG-055: PostgreSQL uses connection pool for async operations.
        """
        checkpoint.updated_at = datetime.now(UTC)

        if self._backend_type == "postgresql":
            # PostgreSQL async save
            await self._ensure_backend_initialized()
            await self._postgres_backend.save_checkpoint(checkpoint)
        else:
            # SQLite save via writer connection
            conn = await self._ensure_writer_connection()
            await asyncio.to_thread(self._save_checkpoint_sync, conn, checkpoint)

        self._checkpoint = checkpoint

        # Sync metadata to filesystem (denormalized cache for CLI)
        self._sync_metadata_to_disk()

        logger.debug("Saved loop checkpoint: loop=%s status=%s", self.loop_id, checkpoint.status)

    def _save_checkpoint_sync(
        self, conn: sqlite3.Connection, checkpoint: AgentLoopCheckpoint
    ) -> None:
        """Sync save of checkpoint executed in thread pool.

        Bug 5.3 fix: Uses UPDATE (not INSERT OR REPLACE) for agentloop_loops.
        Preserves daemon-managed lifecycle statuses (detached, paused, archived)
        via CASE WHEN — if the daemon changed status between subprocess load
        and save, the subprocess preserves it instead of clobbering.
        Also preserves daemon-managed fields: client_workspace, detached_at,
        created_at, schema_version.
        """
        # Serialize complex structures to JSON strings
        thread_ids_json = json.dumps(checkpoint.thread_ids, ensure_ascii=False)
        working_memory_json = checkpoint.working_memory_state.model_dump_json()
        thread_health_json = checkpoint.thread_health_metrics.model_dump_json()

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
                updated_at = ?
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
                 created_at, updated_at, schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )

        # Save goal_history to goal_records table
        for goal_record in checkpoint.goal_history:
            logger.debug(
                "save goal: id=%s status=%s iter=%d ledger_msgs=%d done=%s",
                goal_record.goal_id,
                goal_record.status,
                goal_record.iteration,
                len(goal_record.loop_messages),
                goal_record.completed_at.isoformat() if goal_record.completed_at else "None",
            )

            # Serialize loop_messages to JSON (RFC-214: replaces reason_history/act_history)
            loop_messages_json = json.dumps(
                [msg.model_dump(mode="json") for msg in goal_record.loop_messages],
                ensure_ascii=False,
            )
            completed_at_str = (
                goal_record.completed_at.isoformat() if goal_record.completed_at else None
            )
            # RFC-225: pack enriched fields into extras_jsonb
            extras_payload = {
                "max_iterations": goal_record.max_iterations,
                "current_plan": (
                    goal_record.current_plan.model_dump(mode="json")
                    if goal_record.current_plan is not None
                    else None
                ),
                "completed_step_ids": sorted(goal_record.completed_step_ids),
                "plan_revision_count": goal_record.plan_revision_count,
                "step_results": [s.model_dump(mode="json") for s in goal_record.step_results],
                "evidence_ledger": [e.model_dump(mode="json") for e in goal_record.evidence_ledger],
            }
            extras_json = json.dumps(extras_payload, ensure_ascii=False)

            conn.execute(
                """
                INSERT OR REPLACE INTO goal_records
                (goal_id, loop_id, goal_text, thread_id, iteration, status,
                 loop_messages, goal_completion, evidence_summary,
                 duration_ms, tokens_used, started_at, completed_at, extras_jsonb)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    goal_record.goal_id,
                    checkpoint.loop_id,
                    goal_record.goal_text,
                    goal_record.thread_id,
                    goal_record.iteration,
                    goal_record.status,
                    loop_messages_json,
                    goal_record.goal_completion,
                    goal_record.evidence_summary,
                    goal_record.duration_ms,
                    goal_record.tokens_used,
                    goal_record.started_at.isoformat(),
                    completed_at_str,
                    extras_json,
                ),
            )

        conn.commit()

    def start_new_goal(self, goal: str, max_iterations: int = 10) -> GoalExecutionRecord:
        """Create new goal record and clear working memory (RFC-216).

        Args:
            goal: Goal description
            max_iterations: Maximum iterations for this goal

        Returns:
            New GoalExecutionRecord (thread_id = current_thread_id)

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

        goal_record = GoalExecutionRecord(
            goal_id=goal_id,
            goal_text=goal,
            thread_id=checkpoint.current_thread_id,  # Current thread
            iteration=0,
            max_iterations=max_iterations,
            status="running",  # Implicit
            loop_messages=[],  # RFC-214: Initialize empty ledger
            goal_completion="",
            evidence_summary="",
            duration_ms=0,
            tokens_used=0,
            started_at=now,
            completed_at=None,
        )

        # Clear working memory for new goal
        checkpoint.working_memory_state = WorkingMemoryState(entries=[], spill_files=[])

        return goal_record

    async def finalize_goal(
        self,
        goal_record: GoalExecutionRecord,
        goal_completion: str,
        loop_state: LoopState | None = None,
    ) -> None:
        """Mark goal completed, update loop metrics (RFC-216).

        RFC-225: when ``loop_state`` is provided, mirror the latest plan DAG,
        step results, completed step ids, and evidence ledger into the goal
        record so the AgentLoop checkpoint becomes the durable orchestration log.

        Args:
            goal_record: Goal execution record to finalize.
            goal_completion: Generated goal completion content.
            loop_state: Active LoopState for RFC-225 enrichment mirroring.
        """
        if self._checkpoint is None:
            return

        checkpoint = self._checkpoint

        # BUGFIX: Modify goal_history entry directly (not passed parameter)
        # Pydantic model_copy() creates new instances, so goal_record may be detached
        # Find the goal in goal_history by goal_id and modify that object directly
        target_goal = None
        for g in checkpoint.goal_history:
            if g.goal_id == goal_record.goal_id:
                target_goal = g
                break

        if target_goal is None:
            logger.error("Cannot find goal %s in goal_history", goal_record.goal_id)
            return

        logger.debug(
            "finalize_goal: found id=%s same_obj=%s",
            target_goal.goal_id,
            target_goal is goal_record,
        )

        # Update goal record status (modify history object directly)
        target_goal.status = "completed"
        target_goal.goal_completion = goal_completion
        target_goal.completed_at = datetime.now(UTC)

        # RFC-225: mirror LoopState orchestration overlay into the goal record
        if loop_state is not None:
            if loop_state.current_decision is not None:
                # Snapshot the latest plan + decision as the goal's final plan DAG.
                from soothe.core.loop.state.schemas import PlanResult as _PlanResult

                target_goal.current_plan = _PlanResult(
                    status="done",
                    decision=loop_state.current_decision,
                    evidence_summary=loop_state.evidence_summary,
                    goal_progress="complete",
                )
            target_goal.completed_step_ids = set(loop_state.completed_step_ids)
            target_goal.step_results = list(loop_state.step_results)
            target_goal.evidence_ledger = list(loop_state.evidence_ledger)
            target_goal.evidence_summary = (
                loop_state.evidence_summary or target_goal.evidence_summary
            )

        logger.debug(
            "finalize_goal: modified id=%s iter=%d ledger_msgs=%d",
            target_goal.goal_id,
            target_goal.iteration,
            len(target_goal.loop_messages),
        )

        # Update loop metrics
        checkpoint.total_goals_completed += 1
        checkpoint.total_duration_ms += target_goal.duration_ms
        checkpoint.total_tokens_used += target_goal.tokens_used

        # Update thread health (reset consecutive failures on success)
        checkpoint.thread_health_metrics.consecutive_goal_failures = 0
        checkpoint.thread_health_metrics.last_goal_status = "completed"

        # Reset loop state for next goal
        checkpoint.status = "idle"
        checkpoint.current_goal_index = -1  # IG-055: Reset index after goal completion

        await self.save(checkpoint)

        logger.info(
            "Finalized goal %s on thread %s (loop %s)",
            goal_record.goal_id,
            goal_record.thread_id,
            self.loop_id,
        )

    async def record_iteration(
        self,
        goal_record: GoalExecutionRecord,
        iteration: int,
        plan_result: PlanResult,
        decision: AgentDecision | None,  # Allow None for immediate completion
        step_results: list[StepResult],
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
        # Find the goal in goal_history by goal_id and modify that object directly
        target_goal = None
        for g in checkpoint.goal_history:
            if g.goal_id == goal_record.goal_id:
                target_goal = g
                break

        if target_goal is None:
            logger.error("Cannot find goal %s in goal_history", goal_record.goal_id)
            return

        logger.debug(
            "record_iteration: found id=%s same_obj=%s ledger_len=%d",
            target_goal.goal_id,
            target_goal is goal_record,
            len(state.loop_messages),
        )

        # RFC-214: Persist ledger snapshots. ``LoopState`` may hold a distinct list from
        # Pydantic construction or graph merges; keep ``goal_history`` aligned for reload.
        target_goal.loop_messages = [m.model_copy(deep=True) for m in state.loop_messages]

        # Record working memory state
        if working_memory is not None:
            checkpoint.working_memory_state = self._serialize_working_memory(working_memory)

        # Update goal metrics
        target_goal.iteration = iteration + 1
        target_goal.duration_ms += sum(r.duration_ms for r in step_results)
        target_goal.tokens_used = state.total_tokens_used

        logger.debug(
            "record_iteration: updated iter=%d dur=%dms tok=%d ledger=%d",
            target_goal.iteration,
            target_goal.duration_ms,
            target_goal.tokens_used,
            len(target_goal.loop_messages),
        )

        # Save checkpoint
        await self.save(checkpoint)

    async def finalize_loop(self, status: str) -> None:
        """Mark loop finalized (no more goals accepted).

        Args:
            status: Final status (finalized, cancelled)
        """
        if self._checkpoint is None:
            return

        self._checkpoint.status = status
        await self.save(self._checkpoint)

        logger.info("Finalized loop %s (status: %s)", self.loop_id, status)

    async def close(self) -> None:
        """Close backend connection pools (IG-404, IG-406).

        IG-404: Prevent pool exhaustion in concurrent execution.
        IG-406: Shared pools are closed at daemon level, not per-AgentLoop.

        Must be called after AgentLoop completes to release database connections.
        For shared pool mode, only clears references (pool closed at daemon shutdown).
        """
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

    def _sync_metadata_to_disk(self) -> None:
        """Sync checkpoint metadata to filesystem (denormalized cache for CLI).

        SQLite remains source of truth; metadata.json is for convenience.
        Called automatically from _save_checkpoint_to_db() to cover all lifecycle points.
        """
        if self._checkpoint is None:
            return

        metadata = {
            "loop_id": self._checkpoint.loop_id,
            "status": self._checkpoint.status,
            "thread_ids": self._checkpoint.thread_ids,
            "current_thread_id": self._checkpoint.current_thread_id,
            "total_goals_completed": self._checkpoint.total_goals_completed,
            "total_thread_switches": self._checkpoint.total_thread_switches,
            "total_duration_ms": self._checkpoint.total_duration_ms,
            "total_tokens_used": self._checkpoint.total_tokens_used,
            "schema_version": self._checkpoint.schema_version,
            "created_at": self._checkpoint.created_at.isoformat(),
            "updated_at": self._checkpoint.updated_at.isoformat(),
        }

        self.run_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = self.run_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))
        logger.debug("Synced metadata: %s", metadata_path)
