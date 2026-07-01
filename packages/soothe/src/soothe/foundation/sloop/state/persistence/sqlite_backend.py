"""SQLite backend for StrangeLoop checkpoint persistence.

RFC-215: StrangeLoop Persistence Backend Architecture
IG-055: Backend-agnostic implementation with connection pooling
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import aiosqlite

from soothe.foundation.sloop.state.persistence.base_backend import StrangeLoopPersistenceBackend

if TYPE_CHECKING:
    pass

T = TypeVar("T")

logger = logging.getLogger(__name__)

_LOOP_COLUMN_MIGRATIONS: dict[str, str] = {
    "client_workspace_id": "TEXT",
    "is_ephemeral": "INTEGER NOT NULL DEFAULT 0",
    "last_message_at": "TEXT",
    "current_workspace": "TEXT",
    "human_message_count": "INTEGER NOT NULL DEFAULT 0",
    "ai_message_count": "INTEGER NOT NULL DEFAULT 0",
    "execution_checkpoint": "TEXT",  # RFC-626 Phase 3: ExecutionCheckpoint JSON blob
    "resume_topic": "TEXT",
}

# RFC-225 / IG-445: enriched GoalExecutionRecord fields packed as JSON
# into one column to keep the goal_records schema additive.
_GOAL_RECORD_COLUMN_MIGRATIONS: dict[str, str] = {
    "extras_jsonb": "TEXT",
}


class SQLitePersistenceBackend(StrangeLoopPersistenceBackend):
    """SQLite backend for StrangeLoop checkpoint persistence.

    IG-055: Backend-agnostic implementation with instance-level connection pooling.
    """

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
        self._writer_thread_lock = threading.Lock()

    async def _writer_to_thread(self, sync_fn: Callable[..., T], *args: Any) -> T:
        """Run ``sync_fn(self._writer_conn, *args)`` with serialized SQLite writer access."""
        await self._ensure_pool_initialized()
        return await asyncio.to_thread(self._exec_on_writer_locked, sync_fn, *args)

    def _exec_on_writer_locked(self, sync_fn: Callable[..., T], *args: Any) -> T:
        with self._writer_thread_lock:
            conn = self._writer_conn
            if conn is None:
                msg = "SQLite persistence writer connection is not available"
                raise RuntimeError(msg)
            return sync_fn(conn, *args)

    async def _ensure_pool_initialized(self) -> None:
        """Lazy pool initialization."""
        if self._writer_conn is None:
            async with self._init_lock:
                if self._writer_conn is None:
                    await asyncio.to_thread(self._init_writer_sync)

    def _init_writer_sync(self) -> None:
        """Initialize writer connection with WAL mode."""
        with self._writer_thread_lock:
            if self._writer_conn is not None:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
            self._writer_conn.execute("PRAGMA busy_timeout=60000")
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
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        for i in range(self._pool_size):
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=60000")
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
        """Register new StrangeLoop in database."""
        await self._writer_to_thread(
            self._register_loop_sync,
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
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """
            INSERT INTO agentloop_loops
            (loop_id, thread_ids, current_thread_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (loop_id) DO UPDATE SET
                thread_ids = excluded.thread_ids,
                current_thread_id = excluded.current_thread_id,
                status = excluded.status,
                updated_at = excluded.updated_at
        """,
            (
                loop_id,
                json.dumps(thread_ids),
                current_thread_id,
                status,
                now,
                now,
            ),
        )
        conn.commit()
        logger.debug("Registered loop: loop=%s threads=%s", loop_id, thread_ids)

    async def get_loop_metadata(self, loop_id: str) -> dict | None:
        """Get loop metadata for daemon reconstruction."""
        return await self._writer_to_thread(self._get_loop_metadata_sync, loop_id)

    def _get_loop_metadata_sync(self, conn: sqlite3.Connection, loop_id: str) -> dict | None:
        """Sync get loop metadata."""
        cursor = conn.execute(
            """
            SELECT thread_ids, current_thread_id, status, created_at, updated_at,
                   total_goals_completed, total_thread_switches,
                   total_duration_ms, total_tokens_used, schema_version,
                   client_workspace, detached_at, user_id, client_workspace_id,
                   is_ephemeral, last_message_at, current_workspace,
                   human_message_count, ai_message_count, execution_checkpoint,
                   resume_topic
            FROM agentloop_loops WHERE loop_id = ?
        """,
            (loop_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return {
            "loop_id": loop_id,
            "thread_ids": json.loads(row[0]) if row[0] else [],
            "current_thread_id": row[1],
            "status": row[2],
            "created_at": row[3],
            "updated_at": row[4],
            "total_goals_completed": row[5],
            "total_thread_switches": row[6],
            "total_duration_ms": row[7],
            "total_tokens_used": row[8],
            "schema_version": row[9],
            "client_workspace": row[10],
            "detached_at": row[11],
            "user_id": row[12],
            "client_workspace_id": row[13],
            "is_ephemeral": bool(row[14]) if row[14] is not None else False,
            "last_message_at": row[15],
            "current_workspace": row[16],
            "human_message_count": row[17] or 0,
            "ai_message_count": row[18] or 0,
            "execution_checkpoint": json.loads(row[19]) if row[19] else None,
            "resume_topic": row[20],
        }

    async def update_loop_metadata(self, loop_id: str, **fields: Any) -> None:
        """Partially update loop metadata fields."""
        await self._writer_to_thread(self._update_loop_metadata_sync, loop_id, fields)

    def _update_loop_metadata_sync(
        self, conn: sqlite3.Connection, loop_id: str, fields: dict[str, Any]
    ) -> None:
        """Sync partial update of loop metadata."""
        _allowed = {
            "status",
            "current_thread_id",
            "thread_ids",
            "client_workspace",
            "client_workspace_id",
            "user_id",
            "detached_at",
            "total_goals_completed",
            "total_thread_switches",
            "total_duration_ms",
            "total_tokens_used",
            "updated_at",
            "is_ephemeral",
            "last_message_at",
            "current_workspace",
            "resume_topic",
        }
        updates = {k: v for k, v in fields.items() if k in _allowed}
        if not updates:
            return
        if "is_ephemeral" in updates:
            updates["is_ephemeral"] = 1 if updates["is_ephemeral"] else 0
        if "thread_ids" in updates and isinstance(updates["thread_ids"], list):
            updates["thread_ids"] = json.dumps(updates["thread_ids"])
        updates.setdefault("updated_at", datetime.now(UTC).isoformat())
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [loop_id]
        conn.execute(
            f"UPDATE agentloop_loops SET {set_clause} WHERE loop_id = ?",  # noqa: S608
            params,
        )
        conn.commit()

    async def list_loops(
        self,
        status_filter: str | None = None,
        limit: int = 100,
        exclude_empty: bool = False,
        workspace_filter: str | None = None,
    ) -> list[dict]:
        """Return summary rows for all loops, ordered by created_at DESC.

        Args:
            status_filter: Optional status value to filter by.
            limit: Maximum rows to return.
            exclude_empty: When True, hide loops with zero human and zero AI
                messages (bootstrap-only loops with no real exchange).
            workspace_filter: Optional client_workspace path to filter by.
        """
        return await self._writer_to_thread(
            self._list_loops_sync, status_filter, limit, exclude_empty, workspace_filter
        )

    def _list_loops_sync(
        self,
        conn: sqlite3.Connection,
        status_filter: str | None,
        limit: int,
        exclude_empty: bool,
        workspace_filter: str | None = None,
    ) -> list[dict]:
        """Sync list loops."""
        clauses: list[str] = []
        params: list[Any] = []
        if status_filter:
            clauses.append("status = ?")
            params.append(status_filter)
        if exclude_empty:
            clauses.append("(human_message_count > 0 OR ai_message_count > 0)")
        if workspace_filter:
            clauses.append("client_workspace = ?")
            params.append(workspace_filter)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT loop_id, status, thread_ids, current_thread_id,
                   total_goals_completed, total_thread_switches,
                   created_at, updated_at, client_workspace, detached_at,
                   human_message_count, ai_message_count, last_message_at,
                   resume_topic
            FROM agentloop_loops
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ?
        """  # noqa: S608 — all interpolations are static identifiers.
        params.append(limit)
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()
        result = []
        for row in rows:
            d = {
                "loop_id": row[0],
                "status": row[1],
                "thread_ids": json.loads(row[2]) if row[2] else [],
                "current_thread_id": row[3],
                "total_goals_completed": row[4],
                "total_thread_switches": row[5],
                "created_at": row[6],
                "updated_at": row[7],
                "client_workspace": row[8],
                "detached_at": row[9],
                "human_message_count": row[10] or 0,
                "ai_message_count": row[11] or 0,
                "last_message_at": row[12],
                "resume_topic": row[13],
            }
            result.append(d)
        return result

    async def touch_loop_last_message(self, loop_id: str) -> None:
        """Record user turn activity for ephemeral loop TTL."""
        now = datetime.now(UTC).isoformat()
        await self.update_loop_metadata(loop_id, last_message_at=now, updated_at=now)

    async def heartbeat_loop(self, loop_id: str) -> None:
        """Bump ``updated_at`` so periodic status reconciliation can trust freshness."""
        now = datetime.now(UTC).isoformat()
        await self._writer_to_thread(self._heartbeat_loop_sync, loop_id, now)

    def _heartbeat_loop_sync(
        self,
        conn: sqlite3.Connection,
        loop_id: str,
        now_iso: str,
    ) -> None:
        """Sync heartbeat — single-statement UPDATE; no-op when row is gone."""
        conn.execute(
            "UPDATE agentloop_loops SET updated_at = ? WHERE loop_id = ?",
            (now_iso, loop_id),
        )
        conn.commit()

    async def increment_loop_message_count(
        self,
        loop_id: str,
        human: int = 0,
        ai: int = 0,
    ) -> None:
        """Atomically increment message counters and refresh activity timestamps."""
        if human == 0 and ai == 0:
            return
        now = datetime.now(UTC).isoformat()
        await self._writer_to_thread(
            self._increment_loop_message_count_sync, loop_id, human, ai, now
        )

    def _increment_loop_message_count_sync(
        self,
        conn: sqlite3.Connection,
        loop_id: str,
        human: int,
        ai: int,
        now_iso: str,
    ) -> None:
        """Sync increment counters in a single UPDATE."""
        conn.execute(
            """
            UPDATE agentloop_loops
            SET human_message_count = human_message_count + ?,
                ai_message_count    = ai_message_count + ?,
                last_message_at     = ?,
                updated_at          = ?
            WHERE loop_id = ?
            """,
            (human, ai, now_iso, now_iso, loop_id),
        )
        conn.commit()

    async def list_empty_loops(
        self,
        idle_before: datetime,
        limit: int = 50,
    ) -> list[dict]:
        """Return loops with zero human/AI messages idle since ``idle_before``."""
        idle_iso = idle_before.isoformat()
        return await self._writer_to_thread(
            self._list_empty_loops_sync,
            idle_iso,
            limit,
        )

    def _list_empty_loops_sync(
        self,
        conn: sqlite3.Connection,
        idle_before_iso: str,
        limit: int,
    ) -> list[dict]:
        """Sync list empty loops idle past threshold."""
        cursor = conn.execute(
            """
            SELECT loop_id, thread_ids, current_thread_id, status,
                   client_workspace, current_workspace, user_id, client_workspace_id,
                   last_message_at, created_at, is_ephemeral
            FROM agentloop_loops
            WHERE human_message_count = 0
              AND ai_message_count = 0
              AND status != 'running'
              AND COALESCE(last_message_at, created_at) < ?
            ORDER BY COALESCE(last_message_at, created_at) ASC
            LIMIT ?
            """,
            (idle_before_iso, limit),
        )
        rows = cursor.fetchall()
        result: list[dict] = []
        for row in rows:
            result.append(
                {
                    "loop_id": row[0],
                    "thread_ids": json.loads(row[1]) if row[1] else [],
                    "current_thread_id": row[2],
                    "status": row[3],
                    "client_workspace": row[4],
                    "current_workspace": row[5],
                    "user_id": row[6],
                    "client_workspace_id": row[7],
                    "last_message_at": row[8],
                    "created_at": row[9],
                    "is_ephemeral": bool(row[10]) if row[10] is not None else False,
                }
            )
        return result

    async def list_expired_ephemeral_loops(
        self,
        idle_before: datetime,
        limit: int = 50,
    ) -> list[dict]:
        """Return ephemeral loops idle since ``idle_before`` (excludes running)."""
        idle_iso = idle_before.isoformat()
        return await self._writer_to_thread(
            self._list_expired_ephemeral_loops_sync,
            idle_iso,
            limit,
        )

    def _list_expired_ephemeral_loops_sync(
        self,
        conn: sqlite3.Connection,
        idle_before_iso: str,
        limit: int,
    ) -> list[dict]:
        """Sync list expired ephemeral loops."""
        cursor = conn.execute(
            """
            SELECT loop_id, thread_ids, current_thread_id, status,
                   client_workspace, current_workspace, user_id, client_workspace_id,
                   last_message_at, created_at
            FROM agentloop_loops
            WHERE is_ephemeral = 1
              AND status != 'running'
              AND COALESCE(last_message_at, created_at) < ?
            ORDER BY COALESCE(last_message_at, created_at) ASC
            LIMIT ?
            """,
            (idle_before_iso, limit),
        )
        rows = cursor.fetchall()
        result: list[dict] = []
        for row in rows:
            result.append(
                {
                    "loop_id": row[0],
                    "thread_ids": json.loads(row[1]) if row[1] else [],
                    "current_thread_id": row[2],
                    "status": row[3],
                    "client_workspace": row[4],
                    "current_workspace": row[5],
                    "user_id": row[6],
                    "client_workspace_id": row[7],
                    "last_message_at": row[8],
                    "created_at": row[9],
                    "is_ephemeral": True,
                }
            )
        return result

    async def purge_loop_execution_data(self, loop_id: str) -> None:
        """Delete loop row and related execution tables (keeps workspace dirs)."""
        await self._writer_to_thread(self._purge_loop_execution_data_sync, loop_id)

    def _purge_loop_execution_data_sync(self, conn: sqlite3.Connection, loop_id: str) -> None:
        """Sync purge loop execution data from SQLite."""
        conn.execute("DELETE FROM checkpoint_anchors WHERE loop_id = ?", (loop_id,))
        conn.execute("DELETE FROM failed_branches WHERE loop_id = ?", (loop_id,))
        conn.execute("DELETE FROM goal_records WHERE loop_id = ?", (loop_id,))
        conn.execute("DELETE FROM agentloop_loops WHERE loop_id = ?", (loop_id,))
        conn.commit()
        logger.info("Purged loop execution data from SQLite: loop=%s", loop_id)

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
        await self._writer_to_thread(
            self._save_anchor_sync,
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
            "Saved anchor: loop=%s iter=%d thread=%s checkpoint=%s type=%s",
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
        return await self._writer_to_thread(self._get_anchors_range_sync, loop_id, start, end)

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
        return await self._writer_to_thread(self._get_thread_checkpoints_sync, loop_id, thread_id)

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
        await self._writer_to_thread(
            self._save_branch_sync,
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
        logger.debug("Saved branch: branch=%s loop=%s iter=%d", branch_id, loop_id, iteration)

    async def update_branch_analysis(
        self,
        branch_id: str,
        loop_id: str,
        failure_insights: dict[str, Any],
        avoid_patterns: list[dict[str, Any]],
        suggested_adjustments: list[dict[str, Any]],
    ) -> None:
        """Update branch analysis insights."""
        await self._writer_to_thread(
            self._update_branch_analysis_sync,
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
        logger.debug("Updated branch: branch=%s loop=%s", branch_id, loop_id)

    async def get_failed_branches_for_loop(
        self, loop_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Query failed branches for loop."""
        return await self._writer_to_thread(self._get_branches_sync, loop_id, limit)

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
        return await self._writer_to_thread(self._prune_branches_sync, loop_id, max_age_days)

    def _prune_branches_sync(
        self, conn: sqlite3.Connection, loop_id: str, max_age_days: int
    ) -> int:
        """Sync prune branches."""
        # Calculate cutoff timestamp
        cutoff = datetime.now(UTC) - __import__("datetime").timedelta(days=max_age_days)
        cutoff_str = cutoff.isoformat()

        cursor = conn.execute(
            """
            UPDATE failed_branches
            SET pruned_at = ?
            WHERE loop_id = ?
              AND pruned_at IS NULL
              AND created_at < ?
        """,
            (datetime.now(UTC).isoformat(), loop_id, cutoff_str),
        )
        count = cursor.rowcount
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
        await self._writer_to_thread(
            self._save_goal_sync,
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
            "Saved goal: id=%s loop=%s iter=%d status=%s",
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
        await self._writer_to_thread(
            self._update_goal_sync,
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
            "Updated goal: id=%s loop=%s status=%s dur=%dms",
            goal_id,
            loop_id,
            status,
            duration_ms,
        )

    def _close_writer_locked(self) -> None:
        with self._writer_thread_lock:
            if self._writer_conn:
                self._writer_conn.close()
                self._writer_conn = None

    async def close(self) -> None:
        """Close backend connections."""
        await asyncio.to_thread(self._close_writer_locked)

        for conn in self._reader_pool:
            conn.close()
        self._reader_pool.clear()

        logger.info("SQLite backend closed")

    @staticmethod
    def _ensure_loop_columns(db: sqlite3.Connection) -> None:
        """Add ephemeral-loop columns to existing ``agentloop_loops`` tables."""
        cursor = db.execute("PRAGMA table_info(agentloop_loops)")
        existing = {row[1] for row in cursor.fetchall()}
        for col, typedef in _LOOP_COLUMN_MIGRATIONS.items():
            if col not in existing:
                db.execute(f"ALTER TABLE agentloop_loops ADD COLUMN {col} {typedef}")  # noqa: S608

    @staticmethod
    def _ensure_goal_record_columns(db: sqlite3.Connection) -> None:
        """Add enriched-goal-record columns to existing ``goal_records`` tables (RFC-225)."""
        cursor = db.execute("PRAGMA table_info(goal_records)")
        existing = {row[1] for row in cursor.fetchall()}
        for col, typedef in _GOAL_RECORD_COLUMN_MIGRATIONS.items():
            if col not in existing:
                db.execute(f"ALTER TABLE goal_records ADD COLUMN {col} {typedef}")  # noqa: S608

    @staticmethod
    def _ensure_loop_columns_on_path(db_path: Path) -> None:
        """Migrate ``agentloop_loops`` and ``goal_records`` columns on an existing database file."""
        with sqlite3.connect(db_path) as db:
            SQLitePersistenceBackend._ensure_loop_columns(db)
            SQLitePersistenceBackend._ensure_goal_record_columns(db)
            db.commit()

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
                    schema_version TEXT DEFAULT '3.2',
                    client_workspace TEXT,
                    detached_at TEXT,
                    user_id TEXT,
                    client_workspace_id TEXT,
                    is_ephemeral INTEGER NOT NULL DEFAULT 0,
                    last_message_at TEXT,
                    current_workspace TEXT,
                    human_message_count INTEGER NOT NULL DEFAULT 0,
                    ai_message_count INTEGER NOT NULL DEFAULT 0
                )
            """)

            SQLitePersistenceBackend._ensure_loop_columns(db)

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

            # Create goal_records table (RFC-214: loop_messages replaces reason_history/act_history)
            db.execute("""
                CREATE TABLE IF NOT EXISTS goal_records (
                    goal_id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    goal_text TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    loop_messages TEXT,
                    goal_completion TEXT,
                    evidence_summary TEXT,
                    duration_ms INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    extras_jsonb TEXT,
                    FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id)
                )
            """)

            # Backfill enriched columns on existing databases (RFC-225).
            SQLitePersistenceBackend._ensure_goal_record_columns(db)

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

        logger.info("Initialized SQLite database schema at %s", db_path)

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
                    schema_version TEXT DEFAULT '3.2',
                    client_workspace TEXT,
                    detached_at TEXT,
                    user_id TEXT,
                    client_workspace_id TEXT,
                    is_ephemeral INTEGER NOT NULL DEFAULT 0,
                    last_message_at TEXT,
                    current_workspace TEXT,
                    human_message_count INTEGER NOT NULL DEFAULT 0,
                    ai_message_count INTEGER NOT NULL DEFAULT 0
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
                    extras_jsonb TEXT,
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

        SQLitePersistenceBackend._ensure_loop_columns_on_path(db_path)

        logger.info("Initialized SQLite database schema at %s", db_path)


__all__ = ["SQLitePersistenceBackend"]
