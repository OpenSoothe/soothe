"""SQLite backend for AgentLoop checkpoint persistence.

RFC-409: AgentLoop Persistence Backend Architecture
IG-055: Backend-agnostic implementation with connection pooling
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite

from soothe.cognition.agent_loop.state.persistence.base_backend import AgentLoopPersistenceBackend

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SQLitePersistenceBackend(AgentLoopPersistenceBackend):
    """SQLite backend for AgentLoop checkpoint persistence.

    IG-055: Backend-agnostic implementation with instance-level connection pooling.
    """

    SCHEMA_VERSION = "3.1"

    def __init__(self, db_path: Path, pool_size: int = 5) -> None:
        """Initialize SQLite backend with connection pool.

        Args:
            db_path: Path to SQLite database file.
            pool_size: Number of reader connections (default: 5).
        """
        self.db_path = db_path
        self._pool_size = pool_size
        self._writer_conn: sqlite3.Connection | None = None
        self._reader_pool: list[sqlite3.Connection] = []
        self._pool_semaphore = asyncio.Semaphore(pool_size)
        self._init_lock = asyncio.Lock()

    async def _ensure_pool_initialized(self) -> None:
        """Lazy pool initialization."""
        if self._writer_conn is None:
            async with self._init_lock:
                if self._writer_conn is None:
                    await asyncio.to_thread(self._init_writer_sync)

    def _init_writer_sync(self) -> None:
        """Initialize writer connection with WAL mode."""
        # Ensure database schema
        self.initialize_database_sync(self.db_path)

        # Create writer connection
        self._writer_conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=30,
        )
        self._writer_conn.execute("PRAGMA journal_mode=WAL")
        self._writer_conn.execute("PRAGMA foreign_keys=ON")
        self._writer_conn.row_factory = sqlite3.Row

        logger.info("SQLite backend writer connection initialized at %s", self.db_path)

    async def _get_reader_connection(self) -> sqlite3.Connection:
        """Get reader connection from pool."""
        async with self._pool_semaphore:
            if not self._reader_pool:
                await asyncio.to_thread(self._init_reader_pool_sync)

            # Return connection from pool (round-robin)
            return self._reader_pool[0] if self._reader_pool else self._writer_conn

    def _init_reader_pool_sync(self) -> None:
        """Initialize reader connection pool."""
        for i in range(self._pool_size):
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._reader_pool.append(conn)

        logger.info("SQLite backend reader pool initialized: size=%d", self._pool_size)

    # IG-055: Implement abstract interface methods

    async def register_loop(
        self,
        loop_id: str,
        thread_ids: list[str],
        current_thread_id: str,
        status: str = "running",
    ) -> None:
        """Register new AgentLoop in database."""
        await self._ensure_pool_initialized()
        await asyncio.to_thread(
            self._register_loop_sync,
            self._writer_conn,
            loop_id,
            thread_ids,
            current_thread_id,
            status,
        )

    def _register_loop_sync(
        self,
        conn: sqlite3.Connection,
        loop_id: str,
        thread_ids: list[str],
        current_thread_id: str,
        status: str,
    ) -> None:
        """Sync register loop."""
        conn.execute(
            """
            INSERT OR REPLACE INTO agentloop_loops
            (loop_id, thread_ids, current_thread_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                loop_id,
                json.dumps(thread_ids),
                current_thread_id,
                status,
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
        logger.debug("Registered loop: loop=%s threads=%s", loop_id, thread_ids)

    async def get_loop_metadata(self, loop_id: str) -> dict | None:
        """Get loop metadata for daemon reconstruction."""
        await self._ensure_pool_initialized()
        return await asyncio.to_thread(self._get_loop_metadata_sync, self._writer_conn, loop_id)

    def _get_loop_metadata_sync(self, conn: sqlite3.Connection, loop_id: str) -> dict | None:
        """Sync get loop metadata."""
        cursor = conn.execute(
            """
            SELECT thread_ids, current_thread_id, status, created_at, updated_at
            FROM agentloop_loops WHERE loop_id = ?
        """,
            (loop_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return {
            "loop_id": loop_id,
            "thread_ids": json.loads(row[0]),
            "current_thread_id": row[1],
            "status": row[2],
            "created_at": row[3],
            "updated_at": row[4],
        }

    async def save_checkpoint_anchor(
        self,
        loop_id: str,
        iteration: int,
        thread_id: str,
        checkpoint_id: str,
        anchor_type: str,
        checkpoint_ns: str = "",
        execution_summary: dict[str, Any] | None = None,
    ) -> None:
        """Save iteration checkpoint anchor."""
        await self._ensure_pool_initialized()
        await asyncio.to_thread(
            self._save_anchor_sync,
            self._writer_conn,
            loop_id,
            iteration,
            thread_id,
            checkpoint_id,
            anchor_type,
            checkpoint_ns,
            execution_summary,
        )

    def _save_anchor_sync(
        self,
        conn: sqlite3.Connection,
        loop_id: str,
        iteration: int,
        thread_id: str,
        checkpoint_id: str,
        anchor_type: str,
        checkpoint_ns: str,
        execution_summary: dict[str, Any] | None,
    ) -> None:
        """Sync save anchor."""
        conn.execute(
            """
            INSERT OR REPLACE INTO checkpoint_anchors
            (loop_id, iteration, thread_id, checkpoint_id, checkpoint_ns,
             anchor_type, timestamp, iteration_status, next_action_summary,
             tools_executed, reasoning_decision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                loop_id,
                iteration,
                thread_id,
                checkpoint_id,
                checkpoint_ns,
                anchor_type,
                datetime.now(UTC).isoformat(),
                execution_summary.get("status") if execution_summary else None,
                execution_summary.get("next_action_summary") if execution_summary else None,
                json.dumps(execution_summary.get("tools_executed", []))
                if execution_summary
                else None,
                execution_summary.get("reasoning_decision") if execution_summary else None,
            ),
        )
        conn.commit()
        logger.debug(
            "Saved anchor: loop=%s iteration=%d thread=%s checkpoint=%s type=%s",
            loop_id,
            iteration,
            thread_id,
            checkpoint_id,
            anchor_type,
        )

    async def get_checkpoint_anchors_for_range(
        self, loop_id: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        """Query checkpoint anchors for iteration range."""
        await self._ensure_pool_initialized()
        return await asyncio.to_thread(
            self._get_anchors_range_sync, self._writer_conn, loop_id, start, end
        )

    def _deserialize_anchor_json_fields(self, row_dict: dict[str, Any]) -> dict[str, Any]:
        """Deserialize JSON fields and timestamp fields in anchor row."""
        from datetime import datetime

        # Deserialize tools_executed if present and not None
        if "tools_executed" in row_dict and row_dict["tools_executed"] is not None:
            row_dict["tools_executed"] = json.loads(row_dict["tools_executed"])

        # Deserialize timestamp field from ISO string to datetime
        if "timestamp" in row_dict and row_dict["timestamp"] is not None:
            row_dict["timestamp"] = datetime.fromisoformat(row_dict["timestamp"])

        return row_dict

    def _deserialize_branch_json_fields(self, row_dict: dict[str, Any]) -> dict[str, Any]:
        """Deserialize JSON fields and timestamp fields in branch row."""
        from datetime import datetime

        # Deserialize execution_path if present and not None
        if "execution_path" in row_dict and row_dict["execution_path"] is not None:
            row_dict["execution_path"] = json.loads(row_dict["execution_path"])
        # Deserialize failure_insights if present and not None
        if "failure_insights" in row_dict and row_dict["failure_insights"] is not None:
            row_dict["failure_insights"] = json.loads(row_dict["failure_insights"])
        # Deserialize avoid_patterns if present and not None
        if "avoid_patterns" in row_dict and row_dict["avoid_patterns"] is not None:
            row_dict["avoid_patterns"] = json.loads(row_dict["avoid_patterns"])
        # Deserialize suggested_adjustments if present and not None
        if "suggested_adjustments" in row_dict and row_dict["suggested_adjustments"] is not None:
            row_dict["suggested_adjustments"] = json.loads(row_dict["suggested_adjustments"])

        # Deserialize timestamp fields from ISO strings to datetime objects
        timestamp_fields = ["created_at", "analyzed_at", "pruned_at", "retry_initiated_at"]
        for field in timestamp_fields:
            if field in row_dict and row_dict[field] is not None:
                row_dict[field] = datetime.fromisoformat(row_dict[field])

        return row_dict

    def _get_anchors_range_sync(
        self, conn: sqlite3.Connection, loop_id: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        """Sync query anchors."""
        cursor = conn.execute(
            """
            SELECT anchor_id, loop_id, iteration, thread_id, checkpoint_id, checkpoint_ns,
                   anchor_type, timestamp, iteration_status, next_action_summary,
                   tools_executed, reasoning_decision
            FROM checkpoint_anchors
            WHERE loop_id = ? AND iteration >= ? AND iteration <= ?
            ORDER BY iteration ASC, anchor_type ASC
        """,
            (loop_id, start, end),
        )
        rows = cursor.fetchall()
        return [self._deserialize_anchor_json_fields(dict(row)) for row in rows]

    async def get_thread_checkpoints_for_loop(
        self, loop_id: str, thread_id: str
    ) -> list[dict[str, Any]]:
        """Query checkpoint anchors for specific thread."""
        await self._ensure_pool_initialized()
        return await asyncio.to_thread(
            self._get_thread_checkpoints_sync, self._writer_conn, loop_id, thread_id
        )

    def _get_thread_checkpoints_sync(
        self, conn: sqlite3.Connection, loop_id: str, thread_id: str | None
    ) -> list[dict[str, Any]]:
        """Sync query thread checkpoints.

        Args:
            conn: SQLite connection
            loop_id: Loop identifier
            thread_id: Thread identifier (None = query all threads)
        """
        if thread_id is None:
            # Query all threads for this loop
            cursor = conn.execute(
                """
                SELECT anchor_id, loop_id, iteration, thread_id, checkpoint_id, checkpoint_ns,
                       anchor_type, timestamp, iteration_status, next_action_summary,
                       tools_executed, reasoning_decision
                FROM checkpoint_anchors
                WHERE loop_id = ?
                ORDER BY iteration ASC
            """,
                (loop_id,),
            )
        else:
            # Query specific thread
            cursor = conn.execute(
                """
                SELECT anchor_id, loop_id, iteration, thread_id, checkpoint_id, checkpoint_ns,
                       anchor_type, timestamp, iteration_status, next_action_summary,
                       tools_executed, reasoning_decision
                FROM checkpoint_anchors
                WHERE loop_id = ? AND thread_id = ?
                ORDER BY iteration ASC
            """,
                (loop_id, thread_id),
            )
        rows = cursor.fetchall()
        return [self._deserialize_anchor_json_fields(dict(row)) for row in rows]

    async def save_failed_branch(
        self,
        branch_id: str,
        loop_id: str,
        iteration: int,
        thread_id: str,
        root_checkpoint_id: str,
        failure_checkpoint_id: str,
        failure_reason: str,
        execution_path: list[dict[str, Any]],
    ) -> None:
        """Save failed branch record."""
        await self._ensure_pool_initialized()
        await asyncio.to_thread(
            self._save_branch_sync,
            self._writer_conn,
            branch_id,
            loop_id,
            iteration,
            thread_id,
            root_checkpoint_id,
            failure_checkpoint_id,
            failure_reason,
            execution_path,
        )

    def _save_branch_sync(
        self,
        conn: sqlite3.Connection,
        branch_id: str,
        loop_id: str,
        iteration: int,
        thread_id: str,
        root_checkpoint_id: str,
        failure_checkpoint_id: str,
        failure_reason: str,
        execution_path: list[dict[str, Any]],
    ) -> None:
        """Sync save branch."""
        conn.execute(
            """
            INSERT INTO failed_branches
            (branch_id, loop_id, iteration, thread_id, root_checkpoint_id,
             failure_checkpoint_id, failure_reason, execution_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                branch_id,
                loop_id,
                iteration,
                thread_id,
                root_checkpoint_id,
                failure_checkpoint_id,
                failure_reason,
                json.dumps(execution_path),
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
        logger.debug("Saved branch: branch=%s loop=%s iteration=%d", branch_id, loop_id, iteration)

    async def update_branch_analysis(
        self,
        branch_id: str,
        loop_id: str,
        failure_insights: dict[str, Any],
        avoid_patterns: list[dict[str, Any]],
        suggested_adjustments: list[dict[str, Any]],
    ) -> None:
        """Update branch analysis insights."""
        await self._ensure_pool_initialized()
        await asyncio.to_thread(
            self._update_branch_analysis_sync,
            self._writer_conn,
            branch_id,
            loop_id,
            failure_insights,
            avoid_patterns,
            suggested_adjustments,
        )

    def _update_branch_analysis_sync(
        self,
        conn: sqlite3.Connection,
        branch_id: str,
        loop_id: str,
        failure_insights: dict[str, Any],
        avoid_patterns: list[dict[str, Any]],
        suggested_adjustments: list[dict[str, Any]],
    ) -> None:
        """Sync update branch analysis."""
        conn.execute(
            """
            UPDATE failed_branches
            SET failure_insights = ?,
                avoid_patterns = ?,
                suggested_adjustments = ?,
                analyzed_at = ?
            WHERE branch_id = ? AND loop_id = ?
        """,
            (
                json.dumps(failure_insights),
                json.dumps(avoid_patterns),
                json.dumps(suggested_adjustments),
                datetime.now(UTC).isoformat(),
                branch_id,
                loop_id,
            ),
        )
        conn.commit()
        logger.debug("Updated branch analysis: branch=%s loop=%s", branch_id, loop_id)

    async def get_failed_branches_for_loop(
        self, loop_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Query failed branches for loop."""
        await self._ensure_pool_initialized()
        return await asyncio.to_thread(self._get_branches_sync, self._writer_conn, loop_id, limit)

    def _get_branches_sync(
        self, conn: sqlite3.Connection, loop_id: str, limit: int
    ) -> list[dict[str, Any]]:
        """Sync query branches."""
        cursor = conn.execute(
            """
            SELECT branch_id, loop_id, iteration, thread_id, root_checkpoint_id,
                   failure_checkpoint_id, failure_reason, execution_path,
                   failure_insights, avoid_patterns, suggested_adjustments,
                   created_at, analyzed_at, pruned_at
            FROM failed_branches
            WHERE loop_id = ? AND pruned_at IS NULL
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (loop_id, limit),
        )
        rows = cursor.fetchall()
        return [self._deserialize_branch_json_fields(dict(row)) for row in rows]

    async def prune_old_branches(self, loop_id: str, max_age_days: int = 30) -> int:
        """Prune old failed branches."""
        await self._ensure_pool_initialized()
        return await asyncio.to_thread(
            self._prune_branches_sync, self._writer_conn, loop_id, max_age_days
        )

    def _prune_branches_sync(
        self, conn: sqlite3.Connection, loop_id: str, max_age_days: int
    ) -> int:
        """Sync prune branches."""
        # Calculate cutoff timestamp
        cutoff = datetime.now(UTC) - __import__("datetime").timedelta(days=max_age_days)
        cutoff_str = cutoff.isoformat()

        conn.execute(
            """
            UPDATE failed_branches
            SET pruned_at = ?
            WHERE loop_id = ?
              AND pruned_at IS NULL
              AND created_at < ?
        """,
            (datetime.now(UTC).isoformat(), loop_id, cutoff_str),
        )
        count = conn.total_changes
        conn.commit()
        logger.info(
            "Pruned %d branches for loop=%s (max_age=%d days)", count, loop_id, max_age_days
        )
        return count

    async def save_goal_record(
        self,
        goal_id: str,
        loop_id: str,
        goal_text: str,
        thread_id: str,
        iteration: int,
        status: str,
        started_at: str,
    ) -> None:
        """Save goal execution record."""
        await self._ensure_pool_initialized()
        await asyncio.to_thread(
            self._save_goal_sync,
            self._writer_conn,
            goal_id,
            loop_id,
            goal_text,
            thread_id,
            iteration,
            status,
            started_at,
        )

    def _save_goal_sync(
        self,
        conn: sqlite3.Connection,
        goal_id: str,
        loop_id: str,
        goal_text: str,
        thread_id: str,
        iteration: int,
        status: str,
        started_at: str,
    ) -> None:
        """Sync save goal."""
        conn.execute(
            """
            INSERT INTO goal_records
            (goal_id, loop_id, goal_text, thread_id, iteration, status, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (goal_id, loop_id, goal_text, thread_id, iteration, status, started_at),
        )
        conn.commit()
        logger.debug(
            "Saved goal: goal=%s loop=%s iteration=%d status=%s",
            goal_id,
            loop_id,
            iteration,
            status,
        )

    async def update_goal_record(
        self,
        goal_id: str,
        loop_id: str,
        status: str,
        goal_completion: str,
        evidence_summary: str,
        duration_ms: int,
        tokens_used: int,
        completed_at: str | None,
    ) -> None:
        """Update goal execution record."""
        await self._ensure_pool_initialized()
        await asyncio.to_thread(
            self._update_goal_sync,
            self._writer_conn,
            goal_id,
            loop_id,
            status,
            goal_completion,
            evidence_summary,
            duration_ms,
            tokens_used,
            completed_at,
        )

    def _update_goal_sync(
        self,
        conn: sqlite3.Connection,
        goal_id: str,
        loop_id: str,
        status: str,
        goal_completion: str,
        evidence_summary: str,
        duration_ms: int,
        tokens_used: int,
        completed_at: str | None,
    ) -> None:
        """Sync update goal."""
        conn.execute(
            """
            UPDATE goal_records
            SET status = ?,
                goal_completion = ?,
                evidence_summary = ?,
                duration_ms = ?,
                tokens_used = ?,
                completed_at = ?
            WHERE goal_id = ? AND loop_id = ?
        """,
            (
                status,
                goal_completion,
                evidence_summary,
                duration_ms,
                tokens_used,
                completed_at,
                goal_id,
                loop_id,
            ),
        )
        conn.commit()
        logger.debug(
            "Updated goal: goal=%s loop=%s status=%s duration=%dms",
            goal_id,
            loop_id,
            status,
            duration_ms,
        )

    async def close(self) -> None:
        """Close backend connections."""
        if self._writer_conn:
            self._writer_conn.close()
            self._writer_conn = None

        for conn in self._reader_pool:
            conn.close()
        self._reader_pool.clear()

        logger.info("SQLite backend closed")

    @staticmethod
    def initialize_database_sync(db_path: Path) -> None:
        """Initialize SQLite database schema (synchronous version).

        Creates tables for:
        - agentloop_loops (metadata)
        - checkpoint_anchors (synchronization)
        - failed_branches (learning history)
        - goal_records (execution history)

        Args:
            db_path: Path to SQLite database file.
        """
        # Ensure parent directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(db_path) as db:
            # Enable FK constraints and WAL mode BEFORE creating tables
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")

            # Create agentloop_loops table
            db.execute("""
                CREATE TABLE IF NOT EXISTS agentloop_loops (
                    loop_id TEXT PRIMARY KEY,
                    thread_ids TEXT NOT NULL,
                    current_thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_goal_index INTEGER DEFAULT -1,
                    working_memory_state TEXT,
                    thread_health_metrics TEXT,
                    total_goals_completed INTEGER DEFAULT 0,
                    total_thread_switches INTEGER DEFAULT 0,
                    total_duration_ms INTEGER DEFAULT 0,
                    total_tokens_used INTEGER DEFAULT 0,
                    thread_switch_pending INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    schema_version TEXT DEFAULT '3.1'
                )
            """)

            # Create checkpoint_anchors table
            db.execute("""
                CREATE TABLE IF NOT EXISTS checkpoint_anchors (
                    anchor_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    loop_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    thread_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    checkpoint_ns TEXT DEFAULT '',
                    anchor_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    iteration_status TEXT,
                    next_action_summary TEXT,
                    tools_executed TEXT,
                    reasoning_decision TEXT,
                    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id),
                    UNIQUE(loop_id, iteration, anchor_type)
                )
            """)

            # Create indexes for checkpoint_anchors
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_anchors_loop_iteration
                ON checkpoint_anchors(loop_id, iteration)
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_anchors_thread
                ON checkpoint_anchors(thread_id)
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_anchors_loop_thread
                ON checkpoint_anchors(loop_id, thread_id)
            """)

            # Create failed_branches table
            db.execute("""
                CREATE TABLE IF NOT EXISTS failed_branches (
                    branch_id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    thread_id TEXT NOT NULL,
                    root_checkpoint_id TEXT NOT NULL,
                    failure_checkpoint_id TEXT NOT NULL,
                    failure_reason TEXT NOT NULL,
                    execution_path TEXT NOT NULL,
                    failure_insights TEXT,
                    avoid_patterns TEXT,
                    suggested_adjustments TEXT,
                    created_at TEXT NOT NULL,
                    analyzed_at TEXT,
                    pruned_at TEXT,
                    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id)
                )
            """)

            # Create indexes for failed_branches
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_branches_loop
                ON failed_branches(loop_id)
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_branches_thread
                ON failed_branches(thread_id)
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_branches_iteration
                ON failed_branches(loop_id, iteration)
            """)

            # Create goal_records table
            db.execute("""
                CREATE TABLE IF NOT EXISTS goal_records (
                    goal_id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    goal_text TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    reason_history TEXT,
                    act_history TEXT,
                    goal_completion TEXT,
                    evidence_summary TEXT,
                    duration_ms INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id)
                )
            """)

            # Create indexes for goal_records
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_goals_loop
                ON goal_records(loop_id)
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_goals_thread
                ON goal_records(thread_id)
            """)

            db.commit()

        # Migrate existing records to current schema version
        SQLitePersistenceBackend.migrate_schema_version(db_path)

        logger.info("Initialized SQLite database schema at %s", db_path)

    @staticmethod
    def migrate_schema_version(db_path: Path, target_version: str = "3.1") -> None:
        """Migrate existing loop records to target schema version.

        Args:
            db_path: Path to SQLite database file.
            target_version: Target schema version (default: 3.1)
        """
        if not db_path.exists():
            return

        with sqlite3.connect(db_path) as db:
            db.execute("PRAGMA foreign_keys=ON")

            # Check if there are any loops
            count_result = db.execute("SELECT COUNT(*) FROM agentloop_loops").fetchone()
            loop_count = count_result[0] if count_result else 0

            if loop_count == 0:
                return

            # Update schema version for all loops
            logger.info(
                "Migrating schema version to %s for %d existing loops",
                target_version,
                loop_count,
            )
            db.execute("UPDATE agentloop_loops SET schema_version = ?", (target_version,))
            db.commit()
            logger.info("Schema migration completed successfully")

    @staticmethod
    async def initialize_database(db_path: Path) -> None:
        """Initialize SQLite database schema (async version).

        Creates tables for:
        - agentloop_loops (metadata)
        - checkpoint_anchors (synchronization)
        - failed_branches (learning history)
        - goal_records (execution history)

        Args:
            db_path: Path to SQLite database file.
        """
        # Ensure parent directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(db_path) as db:
            # Enable FK constraints and WAL mode BEFORE creating tables
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_mode=WAL")

            # Create agentloop_loops table (MISSING in async version - add it)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agentloop_loops (
                    loop_id TEXT PRIMARY KEY,
                    thread_ids TEXT NOT NULL,
                    current_thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_goal_index INTEGER DEFAULT -1,
                    working_memory_state TEXT,
                    thread_health_metrics TEXT,
                    total_goals_completed INTEGER DEFAULT 0,
                    total_thread_switches INTEGER DEFAULT 0,
                    total_duration_ms INTEGER DEFAULT 0,
                    total_tokens_used INTEGER DEFAULT 0,
                    thread_switch_pending INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    schema_version TEXT DEFAULT '3.1'
                )
            """)

            # Create checkpoint_anchors table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS checkpoint_anchors (
                    anchor_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    loop_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    thread_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    checkpoint_ns TEXT DEFAULT '',
                    anchor_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    iteration_status TEXT,
                    next_action_summary TEXT,
                    tools_executed TEXT,
                    reasoning_decision TEXT,
                    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id),
                    UNIQUE(loop_id, iteration, anchor_type)
                )
            """)

            # Create indexes for checkpoint_anchors
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_anchors_loop_iteration
                ON checkpoint_anchors(loop_id, iteration)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_anchors_thread
                ON checkpoint_anchors(thread_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_anchors_loop_thread
                ON checkpoint_anchors(loop_id, thread_id)
            """)

            # Create failed_branches table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS failed_branches (
                    branch_id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    thread_id TEXT NOT NULL,
                    root_checkpoint_id TEXT NOT NULL,
                    failure_checkpoint_id TEXT NOT NULL,
                    failure_reason TEXT NOT NULL,
                    execution_path TEXT NOT NULL,
                    failure_insights TEXT,
                    avoid_patterns TEXT,
                    suggested_adjustments TEXT,
                    created_at TEXT NOT NULL,
                    analyzed_at TEXT,
                    pruned_at TEXT,
                    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id)
                )
            """)

            # Create indexes for failed_branches
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_branches_loop
                ON failed_branches(loop_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_branches_thread
                ON failed_branches(thread_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_branches_iteration
                ON failed_branches(loop_id, iteration)
            """)

            # Create goal_records table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS goal_records (
                    goal_id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    goal_text TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    reason_history TEXT,
                    act_history TEXT,
                    goal_completion TEXT,
                    evidence_summary TEXT,
                    duration_ms INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id)
                )
            """)

            # Create indexes for goal_records
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_goals_loop
                ON goal_records(loop_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_goals_thread
                ON goal_records(thread_id)
            """)

            await db.commit()

        logger.info("Initialized SQLite database schema at %s", db_path)


__all__ = ["SQLitePersistenceBackend"]
