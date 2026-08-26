"""SQLite backend for StrangeLoop checkpoint persistence.

RFC-215: StrangeLoop Persistence Backend Architecture
Backend-agnostic implementation with connection pooling
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from soothe.sloop.checkpoints.base_backend import StrangeLoopPersistenceBackend

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

# RFC-626: pre-slim goal_records columns upgraded on first open.
_LEGACY_GOAL_RECORD_COLUMNS = frozenset(
    {
        "goal_text",
        "iteration",
        "loop_messages",
        "goal_completion",
        "evidence_summary",
        "reason_history",
        "act_history",
        "extras_jsonb",
    }
)
_SLIM_GOAL_RECORD_COLUMNS = frozenset(
    {
        "goal_id",
        "loop_id",
        "thread_id",
        "status",
        "duration_ms",
        "tokens_used",
        "started_at",
        "completed_at",
    }
)


class SQLitePersistenceBackend(StrangeLoopPersistenceBackend):
    """SQLite backend for StrangeLoop checkpoint persistence.

    / RFC-801: process-scoped ``SqliteStoreRuntime`` per database file.
    """

    def __init__(self, db_path: Path, pool_size: int = 5) -> None:
        """Initialize SQLite backend backed by ``SqliteRuntimeRegistry``.

        Args:
            db_path: Path to SQLite database file.
            pool_size: Reader pool size for the Runtime (default: 5).
        """
        from soothe_nano.config.models import SqliteRuntimeConfig
        from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize_database_sync(self.db_path)
        self._runtime = SqliteRuntimeRegistry.acquire(
            self.db_path,
            SqliteRuntimeConfig(reader_pool_size=pool_size),
        )
        self._registry_path = self.db_path
        logger.info(
            "SQLite backend using SqliteStoreRuntime path=%s pool=%d",
            self.db_path,
            pool_size,
        )

    async def _writer_to_thread(self, sync_fn: Callable[..., T], *args: Any) -> T:
        """Run ``sync_fn(conn, *args)`` on the process Runtime writer."""
        return await self._runtime.run_write(lambda conn: sync_fn(conn, *args))

    async def _reader_to_thread(self, sync_fn: Callable[..., T], *args: Any) -> T:
        """Run ``sync_fn(conn, *args)`` on a leased Runtime reader."""
        return await self._runtime.run_read(lambda conn: sync_fn(conn, *args))

    # Implement abstract interface methods

    async def register_loop(
        self,
        loop_id: str,
        current_thread_id: str,
        status: str = "running",
    ) -> None:
        """Register new StrangeLoop in database."""
        await self._writer_to_thread(
            self._register_loop_sync,
            loop_id,
            current_thread_id,
            status,
        )

    def _register_loop_sync(
        self,
        conn: sqlite3.Connection,
        loop_id: str,
        current_thread_id: str,
        status: str,
    ) -> None:
        """Sync register loop."""
        now = datetime.now(UTC).isoformat()
        # Seed '[]' — the column persists StrangeLoopCheckpoint.thread_ids (the
        # checkpoint model field, written by sloop_manager on first save). Loop
        # metadata no longer indexes threads (IG-764); the '[]' placeholder
        # satisfies legacy NOT NULL constraints until sloop_manager overwrites it.
        conn.execute(
            """
            INSERT INTO agentloop_loops
            (loop_id, thread_ids, current_thread_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (loop_id) DO UPDATE SET
                current_thread_id = excluded.current_thread_id,
                status = excluded.status,
                updated_at = excluded.updated_at
        """,
            (
                loop_id,
                "[]",
                current_thread_id,
                status,
                now,
                now,
            ),
        )
        logger.debug("Registered loop: loop=%s thread=%s", loop_id, current_thread_id)

    async def get_loop_metadata(self, loop_id: str) -> dict | None:
        """Get loop metadata for daemon reconstruction."""
        return await self._reader_to_thread(self._get_loop_metadata_sync, loop_id)

    def _get_loop_metadata_sync(self, conn: sqlite3.Connection, loop_id: str) -> dict | None:
        """Sync get loop metadata."""
        cursor = conn.execute(
            """
            SELECT current_thread_id, status, created_at, updated_at,
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
            "current_thread_id": row[0],
            "status": row[1],
            "created_at": row[2],
            "updated_at": row[3],
            "total_goals_completed": row[4],
            "total_thread_switches": row[5],
            "total_duration_ms": row[6],
            "total_tokens_used": row[7],
            "schema_version": row[8],
            "client_workspace": row[9],
            "detached_at": row[10],
            "user_id": row[11],
            "client_workspace_id": row[12],
            "is_ephemeral": bool(row[13]) if row[13] is not None else False,
            "last_message_at": row[14],
            "current_workspace": row[15],
            "human_message_count": row[16] or 0,
            "ai_message_count": row[17] or 0,
            "execution_checkpoint": json.loads(row[18]) if row[18] else None,
            "resume_topic": row[19],
        }

    async def update_loop_metadata(
        self, loop_id: str, *, force_status: bool = False, **fields: Any
    ) -> None:
        """Partially update loop metadata fields.

        Args:
            loop_id: Loop identifier.
            force_status: When True, bypass the RFC-225 goal-count guard so a
                caller with authority (e.g. the stale-loop reconciler demoting a
                confirmed-dead zombie) can write ``status`` even when the loop
                already has goals. StrangeLoop remains the authoritative writer
                for the normal path; this flag is reserved for recovery.
            **fields: Column names and values to update.
        """
        await self._writer_to_thread(self._update_loop_metadata_sync, loop_id, fields, force_status)

    def _update_loop_metadata_sync(
        self,
        conn: sqlite3.Connection,
        loop_id: str,
        fields: dict[str, Any],
        force_status: bool = False,
    ) -> None:
        """Sync partial update of loop metadata."""
        _allowed = {
            "status",
            "current_thread_id",
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
        # RFC-225: drop ``status`` from external metadata writes when the loop
        # already has goals. StrangeLoop is the authoritative writer then.
        # ``force_status`` bypasses this for the stale-loop reconciler, which
        # must demote confirmed-dead zombies (no active runner, past the
        # staleness threshold) that would otherwise linger as ``running``.
        local_updates = updates.copy()
        if "status" in local_updates and not force_status:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM goal_records WHERE loop_id = ?",
                (loop_id,),
            )
            row = cursor.fetchone()
            goal_count = int(row[0]) if row else 0
            if goal_count > 0:
                local_updates.pop("status", None)
                if not local_updates:
                    return
        if "is_ephemeral" in local_updates:
            local_updates["is_ephemeral"] = 1 if local_updates["is_ephemeral"] else 0
        local_updates.setdefault("updated_at", datetime.now(UTC).isoformat())
        set_clause = ", ".join(f"{k} = ?" for k in local_updates)
        params = list(local_updates.values()) + [loop_id]
        conn.execute(
            f"UPDATE agentloop_loops SET {set_clause} WHERE loop_id = ?",  # noqa: S608
            params,
        )

    async def mark_running_goals_failed(self, loop_id: str) -> int:
        """Mark a loop's still-``running`` goal_records as ``failed``.

        Called by the stale-loop reconciler alongside a force-demote of the
        loop row to ``idle``. A crashed loop may leave goals stuck in the
        ``running`` state with no ``completed_at``; this closes them so the
        goal DAG reflects reality instead of lingering forever.

        Returns the count of goal rows updated.
        """
        return await self._writer_to_thread(self._mark_running_goals_failed_sync, loop_id)

    def _mark_running_goals_failed_sync(self, conn: sqlite3.Connection, loop_id: str) -> int:
        now = datetime.now(UTC).isoformat()
        cursor = conn.execute(
            """
            UPDATE goal_records
            SET status = 'failed', completed_at = ?
            WHERE loop_id = ? AND status = 'running'
            """,  # noqa: S608
            (now, loop_id),
        )
        return int(cursor.rowcount or 0)

    async def set_resume_topic_once(self, loop_id: str, topic: str) -> bool:
        """Write resume topic only when the loop row has no topic yet."""
        return await self._writer_to_thread(
            self._set_resume_topic_once_sync,
            loop_id,
            topic.strip(),
        )

    def _set_resume_topic_once_sync(
        self,
        conn: sqlite3.Connection,
        loop_id: str,
        topic: str,
    ) -> bool:
        cursor = conn.execute(
            """
            UPDATE agentloop_loops
            SET resume_topic = ?
            WHERE loop_id = ?
              AND (resume_topic IS NULL OR TRIM(resume_topic) = '')
            """,
            (topic, loop_id),
        )
        return bool(cursor.rowcount)

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
        return await self._reader_to_thread(
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
            SELECT loop_id, status, current_thread_id,
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
                "current_thread_id": row[2],
                "total_goals_completed": row[3],
                "total_thread_switches": row[4],
                "created_at": row[5],
                "updated_at": row[6],
                "client_workspace": row[7],
                "detached_at": row[8],
                "human_message_count": row[9] or 0,
                "ai_message_count": row[10] or 0,
                "last_message_at": row[11],
                "resume_topic": row[12],
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
        """Sync list empty loops idle past threshold.

        Includes rows still marked ``status="running"``: the GC purge gate
        performs a live-runner check (``_loop_has_active_runner``), so a
        stale ``running`` status (zombie) is reclaimable. Excluding them
        here would hide zombies from GC discovery entirely.
        """
        cursor = conn.execute(
            """
            SELECT loop_id, current_thread_id, status,
                   client_workspace, current_workspace, user_id, client_workspace_id,
                   last_message_at, created_at, is_ephemeral
            FROM agentloop_loops
            WHERE human_message_count = 0
              AND ai_message_count = 0
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
                    "current_thread_id": row[1],
                    "status": row[2],
                    "client_workspace": row[3],
                    "current_workspace": row[4],
                    "user_id": row[5],
                    "client_workspace_id": row[6],
                    "last_message_at": row[7],
                    "created_at": row[8],
                    "is_ephemeral": bool(row[9]) if row[9] is not None else False,
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
        """Sync list expired ephemeral loops.

        Includes rows still marked ``status="running"``: the GC purge gate
        performs a live-runner check (``_loop_has_active_runner``), so a
        stale ``running`` status (zombie) is reclaimable.
        """
        cursor = conn.execute(
            """
            SELECT loop_id, current_thread_id, status,
                   client_workspace, current_workspace, user_id, client_workspace_id,
                   last_message_at, created_at
            FROM agentloop_loops
            WHERE is_ephemeral = 1
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
                    "current_thread_id": row[1],
                    "status": row[2],
                    "client_workspace": row[3],
                    "current_workspace": row[4],
                    "user_id": row[5],
                    "client_workspace_id": row[6],
                    "last_message_at": row[7],
                    "created_at": row[8],
                    "is_ephemeral": True,
                }
            )
        return result

    async def purge_loop_execution_data(self, loop_id: str) -> None:
        """Delete loop row and related execution tables (keeps workspace dirs)."""
        await self._writer_to_thread(self._purge_loop_execution_data_sync, loop_id)

    def _purge_loop_execution_data_sync(self, conn: sqlite3.Connection, loop_id: str) -> None:
        """Sync purge loop execution data from SQLite."""
        conn.execute("DELETE FROM goal_records WHERE loop_id = ?", (loop_id,))
        conn.execute("DELETE FROM agentloop_loops WHERE loop_id = ?", (loop_id,))
        logger.info("Purged loop execution data from SQLite: loop=%s", loop_id)

    async def save_goal_record(
        self,
        goal_id: str,
        loop_id: str,
        thread_id: str,
        status: str,
        started_at: str,
    ) -> None:
        """Save goal index entry."""
        await self._writer_to_thread(
            self._save_goal_sync,
            goal_id,
            loop_id,
            thread_id,
            status,
            started_at,
        )

    def _save_goal_sync(
        self,
        conn: sqlite3.Connection,
        goal_id: str,
        loop_id: str,
        thread_id: str,
        status: str,
        started_at: str,
    ) -> None:
        """Sync save goal index entry."""
        conn.execute(
            """
            INSERT INTO goal_records
            (goal_id, loop_id, thread_id, status, started_at)
            VALUES (?, ?, ?, ?, ?)
        """,
            (goal_id, loop_id, thread_id, status, started_at),
        )
        logger.debug(
            "Saved goal: id=%s loop=%s thread=%s status=%s",
            goal_id,
            loop_id,
            thread_id,
            status,
        )

    async def update_goal_record(
        self,
        goal_id: str,
        loop_id: str,
        status: str,
        duration_ms: int,
        tokens_used: int,
        completed_at: str | None,
    ) -> None:
        """Update goal index entry."""
        await self._writer_to_thread(
            self._update_goal_sync,
            goal_id,
            loop_id,
            status,
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
        duration_ms: int,
        tokens_used: int,
        completed_at: str | None,
    ) -> None:
        """Sync update goal index entry."""
        conn.execute(
            """
            UPDATE goal_records
            SET status = ?,
                duration_ms = ?,
                tokens_used = ?,
                completed_at = ?
            WHERE goal_id = ? AND loop_id = ?
        """,
            (
                status,
                duration_ms,
                tokens_used,
                completed_at,
                goal_id,
                loop_id,
            ),
        )
        logger.debug(
            "Updated goal: id=%s loop=%s status=%s dur=%dms",
            goal_id,
            loop_id,
            status,
            duration_ms,
        )

    async def close(self) -> None:
        """Release the process Runtime reference for this database path."""
        from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

        await SqliteRuntimeRegistry.release(self._registry_path)
        logger.info("SQLite backend closed path=%s", self.db_path)

    @staticmethod
    def _ensure_loop_columns(db: sqlite3.Connection) -> None:
        """Add ephemeral-loop columns to existing ``agentloop_loops`` tables."""
        cursor = db.execute("PRAGMA table_info(agentloop_loops)")
        existing = {row[1] for row in cursor.fetchall()}
        for col, typedef in _LOOP_COLUMN_MIGRATIONS.items():
            if col not in existing:
                db.execute(f"ALTER TABLE agentloop_loops ADD COLUMN {col} {typedef}")  # noqa: S608

    @staticmethod
    def _migrate_goal_records_slim(db: sqlite3.Connection) -> None:
        """Replace legacy goal_records columns with RFC-626 GoalIndexEntry schema."""
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='goal_records'"
        )
        if cursor.fetchone() is None:
            return

        cursor = db.execute("PRAGMA table_info(goal_records)")
        existing = {row[1] for row in cursor.fetchall()}
        if not existing & _LEGACY_GOAL_RECORD_COLUMNS and existing >= _SLIM_GOAL_RECORD_COLUMNS:
            return

        db.execute("""
            CREATE TABLE IF NOT EXISTS goal_records_new (
                goal_id TEXT PRIMARY KEY,
                loop_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_ms INTEGER DEFAULT 0,
                tokens_used INTEGER DEFAULT 0,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (loop_id) REFERENCES agentloop_loops(loop_id)
            )
        """)
        if existing:
            db.execute("""
                INSERT INTO goal_records_new
                    (goal_id, loop_id, thread_id, status, duration_ms, tokens_used,
                     started_at, completed_at)
                SELECT goal_id, loop_id, thread_id, status,
                       COALESCE(duration_ms, 0), COALESCE(tokens_used, 0),
                       started_at, completed_at
                FROM goal_records
            """)
        db.execute("DROP TABLE goal_records")
        db.execute("ALTER TABLE goal_records_new RENAME TO goal_records")
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_goals_loop
            ON goal_records(loop_id)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_goals_thread
            ON goal_records(thread_id)
        """)

    @staticmethod
    def _ensure_goal_record_columns(db: sqlite3.Connection) -> None:
        """Migrate ``goal_records`` to RFC-626 slim schema when legacy columns exist."""
        SQLitePersistenceBackend._migrate_goal_records_slim(db)

    @staticmethod
    def initialize_database_sync(db_path: Path) -> None:
        """Initialize SQLite database schema (synchronous version).

        Creates tables for:
        - agentloop_loops (metadata)
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
                    thread_ids TEXT NOT NULL DEFAULT '[]',
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
                    schema_version TEXT DEFAULT '5.0',
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

            # Create goal_records table (RFC-626 GoalIndexEntry index)
            db.execute("""
                CREATE TABLE IF NOT EXISTS goal_records (
                    goal_id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_ms INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
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


__all__ = ["SQLitePersistenceBackend"]
