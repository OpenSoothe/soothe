"""AgentLoop State Manager (RFC-205, RFC-608, IG-055).

Manages checkpoint lifecycle: initialize, save, load, recovery.
RFC-608: Multi-thread spanning with loop_id as primary key.
RFC-409: Unified global SQLite persistence backend (loop_checkpoints.db).
IG-055: PostgreSQL backend support using soothe_checkpoints database.
IG-258 Phase 2: Connection pooling to eliminate database lock contention.
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

from soothe.cognition.agent_loop.state.checkpoint import (
    ActWaveRecord,
    AgentLoopCheckpoint,
    GoalExecutionRecord,
    ReasonStepRecord,
    StepExecutionRecord,
    ThreadHealthMetrics,
    ThreadSwitchPolicy,
    WorkingMemoryState,
)
from soothe.cognition.agent_loop.state.persistence.directory_manager import (
    PersistenceDirectoryManager,
)
from soothe.cognition.agent_loop.state.persistence.sqlite_backend import (
    SQLitePersistenceBackend,
)

if TYPE_CHECKING:
    from soothe.cognition.agent_loop.state.schemas import (
        AgentDecision,
        LoopState,
        PlanResult,
        StepResult,
    )
    from soothe.cognition.agent_loop.state.working_memory import LoopWorkingMemory
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class AgentLoopStateManager:
    """Manages AgentLoop checkpoint lifecycle (RFC-608: loop-scoped, multi-thread).

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
    ) -> None:  # noqa: ARG002
        """Initialize with loop_id (primary key), not thread_id.

        IG-055: Configuration-driven backend selection.
        IG-258 Phase 2: Instance-level connection pool.

        Args:
            loop_id: Loop identifier (UUID or existing). None generates new UUID.
            workspace: Optional workspace path (not used for checkpoint storage)
            reader_pool_size: Number of reader connections for concurrent reads (Phase 2).
            config: SootheConfig for backend selection (PostgreSQL vs SQLite).
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

        if config and config.persistence.default_backend == "postgresql":
            self._backend_type = "postgresql"
            self._postgres_dsn = config.resolve_postgres_dsn_for_database("checkpoints")
            logger.info(
                "AgentLoop using PostgreSQL backend (soothe_checkpoints database): loop_id=%s",
                self.loop_id,
            )
        else:
            # SQLite fallback (backward compatibility)
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

        Ensures appropriate backend is ready for operations.
        """
        if self._backend_type == "postgresql":
            if self._postgres_backend is None:
                from soothe.cognition.agent_loop.state.persistence.postgres_backend import (
                    PostgreSQLPersistenceBackend,
                )

                async with self._init_lock:
                    if self._postgres_backend is None:
                        self._postgres_backend = PostgreSQLPersistenceBackend(
                            dsn=self._postgres_dsn, pool_size=self._reader_pool_size
                        )
                        # Schema initialization happens in backend
                        logger.info("AgentLoop PostgreSQL backend ready: loop_id=%s", self.loop_id)
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
        """Create new loop for thread (RFC-608: loop-scoped).

        IG-258 Phase 2: Database schema initialized lazily by writer connection.

        Args:
            thread_id: First thread for this loop
            max_iterations: Maximum loop iterations per goal

        Returns:
            New AgentLoopCheckpoint instance (status=ready_for_next_goal)
        """
        now = datetime.now(UTC)

        checkpoint = AgentLoopCheckpoint(
            loop_id=self.loop_id,
            thread_ids=[thread_id],  # First thread
            current_thread_id=thread_id,
            status="ready_for_next_goal",
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
            schema_version="3.1",  # Match SCHEMA_VERSION constant
        )

        self._checkpoint = checkpoint
        await self._save_checkpoint_to_db(checkpoint)

        logger.info(
            "Initialized loop %s on thread %s (status: ready_for_next_goal)",
            self.loop_id,
            thread_id,
        )

        return checkpoint

    async def load(self) -> AgentLoopCheckpoint | None:
        """Load existing loop checkpoint (RFC-608: by loop_id).

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
                    goal_record = GoalExecutionRecord(
                        goal_id=goal_row[0],
                        goal_text=goal_row[2],
                        thread_id=goal_row[3],
                        iteration=goal_row[4],
                        max_iterations=10,  # Default
                        status=goal_row[5],
                        reason_history=json.loads(goal_row[6]) if goal_row[6] else [],
                        act_history=json.loads(goal_row[7]) if goal_row[7] else [],
                        goal_completion=goal_row[8] or "",
                        evidence_summary=goal_row[9] or "",
                        duration_ms=goal_row[10],
                        tokens_used=goal_row[11],
                        started_at=datetime.fromisoformat(goal_row[12]),
                        completed_at=datetime.fromisoformat(goal_row[13]) if goal_row[13] else None,
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
                if (
                    checkpoint.status == "ready_for_next_goal"
                    and checkpoint.current_goal_index == -1
                ):
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
                   reason_history, act_history, goal_completion, evidence_summary,
                   duration_ms, tokens_used, started_at, completed_at
            FROM goal_records WHERE loop_id = ?
            ORDER BY started_at
            """,
            (loop_id,),
        )
        return cursor.fetchall()

    async def save(self, checkpoint: AgentLoopCheckpoint) -> None:
        """Persist loop checkpoint to SQLite (RFC-608: indexed by loop_id).

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

        logger.debug("Saved loop %s checkpoint (status %s)", self.loop_id, checkpoint.status)

    def _save_checkpoint_sync(
        self, conn: sqlite3.Connection, checkpoint: AgentLoopCheckpoint
    ) -> None:
        """Sync save of checkpoint executed in thread pool."""
        # Serialize complex structures to JSON strings
        thread_ids_json = json.dumps(checkpoint.thread_ids, ensure_ascii=False)
        working_memory_json = checkpoint.working_memory_state.model_dump_json()
        thread_health_json = checkpoint.thread_health_metrics.model_dump_json()

        # Update agentloop_loops table
        conn.execute(
            """
            INSERT OR REPLACE INTO agentloop_loops
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
                "[DEBUG save] Saving goal_record: goal_id=%s, status=%s, iteration=%d, reason_len=%d, act_len=%d, completed_at=%s",
                goal_record.goal_id,
                goal_record.status,
                goal_record.iteration,
                len(goal_record.reason_history),
                len(goal_record.act_history),
                goal_record.completed_at.isoformat() if goal_record.completed_at else None,
            )

            # Serialize complex structures to JSON strings
            reason_history_json = json.dumps(
                [r.model_dump(mode="json") for r in goal_record.reason_history], ensure_ascii=False
            )
            act_history_json = json.dumps(
                [a.model_dump(mode="json") for a in goal_record.act_history], ensure_ascii=False
            )
            completed_at_str = (
                goal_record.completed_at.isoformat() if goal_record.completed_at else None
            )

            conn.execute(
                """
                INSERT OR REPLACE INTO goal_records
                (goal_id, loop_id, goal_text, thread_id, iteration, status,
                 reason_history, act_history, goal_completion, evidence_summary,
                 duration_ms, tokens_used, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    goal_record.goal_id,
                    checkpoint.loop_id,
                    goal_record.goal_text,
                    goal_record.thread_id,
                    goal_record.iteration,
                    goal_record.status,
                    reason_history_json,
                    act_history_json,
                    goal_record.goal_completion,
                    goal_record.evidence_summary,
                    goal_record.duration_ms,
                    goal_record.tokens_used,
                    goal_record.started_at.isoformat(),
                    completed_at_str,
                ),
            )

        conn.commit()

    def start_new_goal(self, goal: str, max_iterations: int = 10) -> GoalExecutionRecord:
        """Create new goal record and clear working memory (RFC-608).

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
            reason_history=[],
            act_history=[],
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

    async def finalize_goal(self, goal_record: GoalExecutionRecord, goal_completion: str) -> None:
        """Mark goal completed, update loop metrics (RFC-608).

        Args:
            goal_record: Goal execution record to finalize
            goal_completion: Generated goal completion content
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
            "[DEBUG finalize_goal] Found target_goal in history: goal_id=%s, object_same=%s",
            target_goal.goal_id,
            target_goal is goal_record,
        )

        # Update goal record status (modify history object directly)
        target_goal.status = "completed"
        target_goal.goal_completion = goal_completion
        target_goal.completed_at = datetime.now(UTC)

        logger.debug(
            "[DEBUG finalize_goal] Modified target_goal: status=%s, iteration=%d, reason_history_len=%d, act_history_len=%d",
            target_goal.status,
            target_goal.iteration,
            len(target_goal.reason_history),
            len(target_goal.act_history),
        )

        # Update loop metrics
        checkpoint.total_goals_completed += 1
        checkpoint.total_duration_ms += target_goal.duration_ms
        checkpoint.total_tokens_used += target_goal.tokens_used

        # Update thread health (reset consecutive failures on success)
        checkpoint.thread_health_metrics.consecutive_goal_failures = 0
        checkpoint.thread_health_metrics.last_goal_status = "completed"

        # Reset loop state for next goal
        checkpoint.status = "ready_for_next_goal"
        checkpoint.current_goal_index = -1  # IG-055: Reset index after goal completion

        await self.save(checkpoint)

        logger.info(
            "Finalized goal %s on thread %s (loop %s)",
            goal_record.goal_id,
            goal_record.thread_id,
            self.loop_id,
        )

    async def execute_thread_switch(self, new_thread_id: str) -> None:
        """Execute thread switch: update checkpoint with new thread (RFC-608, RFC-609).

        Args:
            new_thread_id: New thread to switch to
        """
        if self._checkpoint is None:
            return

        checkpoint = self._checkpoint

        # Add new thread to thread_ids
        checkpoint.thread_ids.append(new_thread_id)
        checkpoint.current_thread_id = new_thread_id
        checkpoint.total_thread_switches += 1

        # RFC-609: Set thread switch flag for Execute briefing injection
        checkpoint.thread_switch_pending = True

        # Reset thread health metrics for new thread
        checkpoint.thread_health_metrics = ThreadHealthMetrics(
            thread_id=new_thread_id, last_updated=datetime.now(UTC)
        )

        await self.save(checkpoint)

        logger.info(
            "Thread switch executed: loop %s → thread %s (switch count: %d, briefing flag set)",
            self.loop_id,
            new_thread_id,
            checkpoint.total_thread_switches,
        )

    def inject_previous_goal_context(self, limit: int = 1) -> list[str]:
        """Inject previous goal completion into Plan phase (RFC-608: same-thread continuation).

        Args:
            limit: Number of previous goals to inject (default: 1)

        Returns:
            List of XML-formatted previous goal context blocks
        """
        if self._checkpoint is None or not self._checkpoint.goal_history:
            return []

        # Get most recent completed goals on current thread
        previous_goals = [
            g for g in self._checkpoint.goal_history[-limit:] if g.status == "completed"
        ]

        if not previous_goals:
            return []

        context_blocks = []
        for goal in previous_goals:
            context_block = (
                f"<previous_goal>\n"
                f"Goal: {goal.goal_text}\n"
                f"Status: {goal.status}\n"
                f"Thread: {goal.thread_id}\n"
                f"Output:\n{goal.goal_completion}\n"
                f"</previous_goal>"
            )
            context_blocks.append(context_block)

        return context_blocks

    def auto_recall_on_thread_switch(
        self, next_goal: str | None, policy: ThreadSwitchPolicy
    ) -> list[str]:
        """Auto /recall knowledge from previous threads on thread switch (RFC-608).

        Args:
            next_goal: Next goal text (for relevance query) or None
            policy: Thread switching policy (knowledge_transfer_limit)

        Returns:
            List of XML-formatted recalled knowledge blocks
        """
        if self._checkpoint is None:
            return []

        checkpoint = self._checkpoint

        # Previous threads (exclude current new thread)
        previous_thread_ids = checkpoint.thread_ids[:-1]

        if not previous_thread_ids:
            return []  # No previous threads

        # Build searchable corpus from previous goal_history
        documents = []
        for goal_record in checkpoint.goal_history:
            if goal_record.thread_id in previous_thread_ids:
                doc_text = f"{goal_record.goal_text}\n{goal_record.goal_completion}"
                documents.append(
                    {
                        "thread_id": goal_record.thread_id,
                        "goal_id": goal_record.goal_id,
                        "goal_text": goal_record.goal_text,
                        "text": doc_text,
                    }
                )

        if not documents:
            return []  # No previous goals to recall

        # TODO: Integrate VectorStoreProtocol for semantic search
        # Placeholder: Return top-K recent goals
        top_k = min(policy.knowledge_transfer_limit, len(documents))

        recalled_knowledge = []
        for doc in documents[-top_k:]:
            excerpt = (
                f"<recalled_knowledge>\n"
                f"From thread {doc['thread_id']}, goal: {doc['goal_text']}\n"
                f"Output:\n{doc['text'][:500]}...\n"
                f"</recalled_knowledge>"
            )
            recalled_knowledge.append(excerpt)

        logger.info(
            "Auto /recall on thread switch: %d knowledge blocks from %d previous threads",
            len(recalled_knowledge),
            len(previous_thread_ids),
        )

        return recalled_knowledge

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
        """Update goal record after each iteration (RFC-608).

        Args:
            goal_record: Goal execution record to update
            iteration: Current iteration number
            plan_result: Plan phase result
            decision: AgentDecision that was executed (or None for immediate completion)
            step_results: Step execution results
            state: LoopState with metrics
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
            "[DEBUG record_iteration] Found target_goal in history: goal_id=%s, object_same=%s",
            target_goal.goal_id,
            target_goal is goal_record,
        )

        # Record Plan step
        reason_record = ReasonStepRecord(
            iteration=iteration,
            timestamp=datetime.now(UTC),
            goal_text=state.goal,
            prior_step_outputs=self._derive_prior_step_outputs(target_goal),
            assessment_reasoning=plan_result.assessment_reasoning,
            plan_reasoning=plan_result.plan_reasoning,
            status=plan_result.status,
            goal_progress=plan_result.goal_progress,
            decision=decision.model_dump() if decision else None,
            next_action=plan_result.next_action,
        )
        target_goal.reason_history.append(reason_record)

        logger.debug(
            "[DEBUG record_iteration] Added reason_record to target_goal, reason_history_len=%d",
            len(target_goal.reason_history),
        )

        # Record Act wave
        act_record = self._build_act_wave_record(iteration, decision, step_results, state)
        target_goal.act_history.append(act_record)

        logger.debug(
            "[DEBUG record_iteration] Added act_record to target_goal, act_history_len=%d",
            len(target_goal.act_history),
        )

        # Record working memory state
        if working_memory is not None:
            checkpoint.working_memory_state = self._serialize_working_memory(working_memory)

        # Update goal metrics
        target_goal.iteration = iteration + 1
        target_goal.duration_ms += act_record.duration_ms
        target_goal.tokens_used = state.total_tokens_used

        logger.debug(
            "[DEBUG record_iteration] Updated target_goal: iteration=%d, duration_ms=%d, tokens=%d",
            target_goal.iteration,
            target_goal.duration_ms,
            target_goal.tokens_used,
        )

        # Save checkpoint
        await self.save(checkpoint)

    def derive_plan_conversation(self, limit: int = 10) -> list[str]:
        """Derive prior conversation from current goal's step outputs.

        Args:
            limit: Maximum step outputs to include

        Returns:
            List of XML-formatted assistant turns
        """
        if self._checkpoint is None or self._checkpoint.current_goal_index < 0:
            return []

        goal_record = self._checkpoint.goal_history[self._checkpoint.current_goal_index]

        conversation = [
            f"<assistant>\n{step.output}\n</assistant>"
            for act_wave in goal_record.act_history
            for step in act_wave.steps
            if step.success and step.output
        ]

        return conversation[-limit:]

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

    def _derive_prior_step_outputs(self, goal_record: GoalExecutionRecord | None) -> list[str]:
        """Get prior step outputs from goal's previous Act waves."""
        if not goal_record or not goal_record.act_history:
            return []

        return [
            step.output
            for act_wave in goal_record.act_history
            for step in act_wave.steps
            if step.success and step.output
        ]

    def _build_act_wave_record(
        self,
        iteration: int,
        decision: AgentDecision | None,
        step_results: list[StepResult],
        state: LoopState,  # noqa: ARG002 - Reserved for future metrics extraction
    ) -> ActWaveRecord:
        """Convert execution results to ActWaveRecord.

        Args:
            iteration: Iteration number
            decision: AgentDecision (None for immediate completion without execution)
            step_results: Step execution results (empty list for no execution)
            state: LoopState with metrics

        Returns:
            ActWaveRecord with step details and metrics
        """
        # Build step execution records
        step_records = []
        step_desc_map = {s.id: s.description for s in decision.steps} if decision else {}

        for result in step_results:
            step_input = step_desc_map.get(result.step_id, "")
            outcome_summary = result.to_evidence_string(truncate=False) if result.success else ""

            step_record = StepExecutionRecord(
                step_id=result.step_id,
                description=step_desc_map.get(result.step_id, ""),
                step_input=step_input,
                success=result.success,
                output=outcome_summary,
                error=result.error,
                tool_calls=[],  # Reserved for future extraction
                subagent_calls=[],  # Reserved for future extraction
            )
            step_records.append(step_record)

        # Aggregate metrics
        total_tool_calls = sum(r.tool_call_count for r in step_results)
        total_subagent_tasks = sum(r.subagent_task_completions for r in step_results)
        hit_cap = any(r.hit_subagent_cap for r in step_results)
        error_count = sum(1 for r in step_results if not r.success)
        duration_ms = sum(r.duration_ms for r in step_results)

        return ActWaveRecord(
            iteration=iteration,
            timestamp=datetime.now(UTC),
            steps=step_records,
            execution_mode=decision.execution_mode if decision else "sequential",  # Handle None
            duration_ms=duration_ms,
            tool_call_count=total_tool_calls,
            subagent_task_count=total_subagent_tasks,
            hit_subagent_cap=hit_cap,
            error_count=error_count,
        )

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
        logger.debug("Synced metadata to disk: %s", metadata_path)
