"""PostgreSQL backend for AgentLoop persistence (RFC-612, IG-055).

Backend-agnostic implementation supporting full AgentLoop persistence operations.
Uses shared soothe_checkpoints database with 4 tables: agentloop_checkpoints,
checkpoint_anchors, failed_branches, goal_records.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from soothe.cognition.agent_loop.state.persistence.base_backend import AgentLoopPersistenceBackend

if TYPE_CHECKING:
    from soothe.cognition.agent_loop.state.checkpoint import AgentLoopCheckpoint

logger = logging.getLogger(__name__)


class PostgreSQLPersistenceBackend(AgentLoopPersistenceBackend):
    """PostgreSQL backend for AgentLoop persistence (RFC-612, IG-055).

    Backend-agnostic implementation using shared soothe_checkpoints database
    with separate tables for checkpoints, anchors, branches, and goals.
    """

    def __init__(self, dsn: str, pool_size: int = 10) -> None:
        """Initialize PostgreSQL backend with DSN and pool configuration.

        Args:
            dsn: PostgreSQL DSN for soothe_checkpoints database.
            pool_size: Connection pool size (default: 10).
        """
        self.dsn = dsn
        self.pool_size = pool_size
        self._pool: AsyncConnectionPool | None = None
        self._init_lock = asyncio.Lock()

    async def _ensure_pool(self) -> AsyncConnectionPool:
        """Lazy connection pool initialization with schema setup.

        Returns:
            Active AsyncConnectionPool instance.
        """
        if self._pool is not None:
            return self._pool

        async with self._init_lock:
            if self._pool is not None:
                return self._pool

            # Create connection pool
            pool = AsyncConnectionPool(
                self.dsn,
                max_size=self.pool_size,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
                open=False,
            )

            # Open pool and initialize schema
            await pool.open()
            await self._initialize_schema(pool)

            self._pool = pool
            logger.info(
                "AgentLoop PostgreSQL backend initialized (soothe_checkpoints database, table=agentloop_checkpoints, pool=%d)",
                self.pool_size,
            )

            return self._pool

    async def _initialize_schema(self, pool: AsyncConnectionPool) -> None:
        """Create AgentLoop checkpoint tables if not exist.

        IG-055: Adds checkpoint_anchors, failed_branches, goal_records tables
        to match SQLite schema structure for backend-agnostic operations.

        Args:
            pool: Connection pool to use for schema creation.
        """
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Create agentloop_checkpoints table (separate from LangGraph checkpoints)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS agentloop_checkpoints (
                        loop_id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW(),
                        checkpoint_data JSONB NOT NULL
                    )
                """)

                # Create indexes for agentloop_checkpoints
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_agentloop_checkpoints_thread_id
                    ON agentloop_checkpoints(thread_id)
                """)

                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_agentloop_checkpoints_status
                    ON agentloop_checkpoints(status)
                """)

                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_agentloop_checkpoints_updated_at
                    ON agentloop_checkpoints(updated_at DESC)
                """)

                # IG-055: Create checkpoint_anchors table (matching SQLite schema lines 65-96)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS checkpoint_anchors (
                        anchor_id SERIAL PRIMARY KEY,
                        loop_id TEXT NOT NULL,
                        iteration INTEGER NOT NULL,
                        thread_id TEXT NOT NULL,
                        checkpoint_id TEXT NOT NULL,
                        checkpoint_ns TEXT DEFAULT '',
                        anchor_type TEXT NOT NULL,
                        timestamp TIMESTAMPTZ NOT NULL,
                        iteration_status TEXT,
                        next_action_summary TEXT,
                        tools_executed JSONB,
                        reasoning_decision TEXT,
                        FOREIGN KEY (loop_id) REFERENCES agentloop_checkpoints(loop_id),
                        UNIQUE(loop_id, iteration, anchor_type)
                    )
                """)

                # Create indexes for checkpoint_anchors (matching SQLite)
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_anchors_loop_iteration
                    ON checkpoint_anchors(loop_id, iteration)
                """)
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_anchors_thread
                    ON checkpoint_anchors(thread_id)
                """)
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_anchors_loop_thread
                    ON checkpoint_anchors(loop_id, thread_id)
                """)

                # IG-055: Create failed_branches table (matching SQLite schema lines 98-131)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS failed_branches (
                        branch_id TEXT PRIMARY KEY,
                        loop_id TEXT NOT NULL,
                        iteration INTEGER NOT NULL,
                        thread_id TEXT NOT NULL,
                        root_checkpoint_id TEXT NOT NULL,
                        failure_checkpoint_id TEXT NOT NULL,
                        failure_reason TEXT NOT NULL,
                        execution_path JSONB NOT NULL,
                        failure_insights JSONB,
                        avoid_patterns JSONB,
                        suggested_adjustments JSONB,
                        created_at TIMESTAMPTZ NOT NULL,
                        analyzed_at TIMESTAMPTZ,
                        pruned_at TIMESTAMPTZ,
                        FOREIGN KEY (loop_id) REFERENCES agentloop_checkpoints(loop_id)
                    )
                """)

                # Create indexes for failed_branches (matching SQLite)
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_branches_loop
                    ON failed_branches(loop_id)
                """)
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_branches_thread
                    ON failed_branches(thread_id)
                """)
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_branches_iteration
                    ON failed_branches(loop_id, iteration)
                """)

                # IG-055: Create goal_records table (matching SQLite schema lines 133-162)
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS goal_records (
                        goal_id TEXT PRIMARY KEY,
                        loop_id TEXT NOT NULL,
                        goal_text TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        iteration INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        reason_history JSONB,
                        act_history JSONB,
                        goal_completion TEXT,
                        evidence_summary TEXT,
                        duration_ms INTEGER DEFAULT 0,
                        tokens_used INTEGER DEFAULT 0,
                        started_at TIMESTAMPTZ NOT NULL,
                        completed_at TIMESTAMPTZ,
                        FOREIGN KEY (loop_id) REFERENCES agentloop_checkpoints(loop_id)
                    )
                """)

                # Create indexes for goal_records (matching SQLite)
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_goals_loop
                    ON goal_records(loop_id)
                """)
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_goals_thread
                    ON goal_records(thread_id)
                """)

                logger.info(
                    "AgentLoop PostgreSQL schema initialized (4 tables: checkpoints, anchors, branches, goals)"
                )

    async def save_checkpoint(self, checkpoint: AgentLoopCheckpoint) -> None:
        """Save AgentLoop checkpoint to PostgreSQL.

        Args:
            checkpoint: AgentLoopCheckpoint to save.
        """
        pool = await self._ensure_pool()

        checkpoint_data = checkpoint.model_dump(mode="json")
        loop_id = checkpoint_data["loop_id"]
        thread_id = checkpoint_data["current_thread_id"]
        status = checkpoint_data["status"]

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO agentloop_checkpoints (loop_id, thread_id, status, checkpoint_data, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (loop_id)
                    DO UPDATE SET
                        thread_id = EXCLUDED.thread_id,
                        status = EXCLUDED.status,
                        checkpoint_data = EXCLUDED.checkpoint_data,
                        updated_at = NOW()
                """,
                    (loop_id, thread_id, status, json.dumps(checkpoint_data)),
                )

                logger.debug("Saved checkpoint: loop=%s", loop_id)

    async def load_checkpoint(self, loop_id: str) -> AgentLoopCheckpoint | None:
        """Load AgentLoop checkpoint from PostgreSQL.

        Args:
            loop_id: Loop identifier to load.

        Returns:
            AgentLoopCheckpoint if found, None otherwise.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT checkpoint_data FROM agentloop_checkpoints WHERE loop_id = %s
                """,
                    (loop_id,),
                )

                result = await cur.fetchone()
                if not result:
                    return None

                # Deserialize checkpoint
                from soothe.cognition.agent_loop.state.checkpoint import AgentLoopCheckpoint

                checkpoint_data = result["checkpoint_data"]
                return AgentLoopCheckpoint.model_validate(checkpoint_data)

    async def delete_checkpoint(self, loop_id: str) -> None:
        """Delete AgentLoop checkpoint from PostgreSQL.

        Args:
            loop_id: Loop identifier to delete.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    DELETE FROM agentloop_checkpoints WHERE loop_id = %s
                """,
                    (loop_id,),
                )

                logger.debug("Deleted checkpoint: loop=%s", loop_id)

    async def list_checkpoints(
        self, thread_id: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List AgentLoop checkpoints with optional filters.

        Args:
            thread_id: Filter by thread_id (optional).
            status: Filter by status (optional).

        Returns:
            List of checkpoint metadata dictionaries.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                if thread_id and status:
                    await cur.execute(
                        """
                        SELECT loop_id, thread_id, status, created_at, updated_at
                        FROM agentloop_checkpoints
                        WHERE thread_id = %s AND status = %s
                        ORDER BY updated_at DESC
                    """,
                        (thread_id, status),
                    )
                elif thread_id:
                    await cur.execute(
                        """
                        SELECT loop_id, thread_id, status, created_at, updated_at
                        FROM agentloop_checkpoints
                        WHERE thread_id = %s
                        ORDER BY updated_at DESC
                    """,
                        (thread_id,),
                    )
                elif status:
                    await cur.execute(
                        """
                        SELECT loop_id, thread_id, status, created_at, updated_at
                        FROM agentloop_checkpoints
                        WHERE status = %s
                        ORDER BY updated_at DESC
                    """,
                        (status,),
                    )
                else:
                    await cur.execute("""
                        SELECT loop_id, thread_id, status, created_at, updated_at
                        FROM agentloop_checkpoints
                        ORDER BY updated_at DESC
                    """)

                results = await cur.fetchall()
                return results

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("AgentLoop PostgreSQL backend closed")

    # IG-055: Implement abstract interface methods

    async def register_loop(
        self,
        loop_id: str,
        thread_ids: list[str],
        current_thread_id: str,
        status: str = "running",
    ) -> None:
        """Register new AgentLoop in database.

        Args:
            loop_id: AgentLoop identifier.
            thread_ids: List of thread IDs associated with this loop.
            current_thread_id: Current active thread ID.
            status: Loop status (default: "running").
        """
        pool = await self._ensure_pool()

        checkpoint_data = {
            "loop_id": loop_id,
            "thread_ids": thread_ids,
            "current_thread_id": current_thread_id,
            "status": status,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO agentloop_checkpoints (loop_id, thread_id, status, checkpoint_data, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (loop_id)
                    DO UPDATE SET
                        thread_id = EXCLUDED.thread_id,
                        status = EXCLUDED.status,
                        checkpoint_data = EXCLUDED.checkpoint_data,
                        updated_at = NOW()
                """,
                    (loop_id, current_thread_id, status, json.dumps(checkpoint_data)),
                )

                logger.debug("Registered loop: loop=%s threads=%s", loop_id, thread_ids)

    async def get_loop_metadata(self, loop_id: str) -> dict | None:
        """Get loop metadata for daemon reconstruction.

        Args:
            loop_id: Loop identifier.

        Returns:
            Loop metadata dict if found, None otherwise.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT checkpoint_data FROM agentloop_checkpoints WHERE loop_id = %s
                """,
                    (loop_id,),
                )

                result = await cur.fetchone()
                if not result:
                    return None

                return result["checkpoint_data"]

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
        """Save iteration checkpoint anchor.

        Args:
            loop_id: AgentLoop identifier.
            iteration: Iteration number.
            thread_id: Thread where checkpoint belongs.
            checkpoint_id: CoreAgent checkpoint_id.
            anchor_type: "iteration_start", "iteration_end", "failure_point".
            checkpoint_ns: CoreAgent checkpoint namespace.
            execution_summary: Optional execution metadata.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO checkpoint_anchors
                    (loop_id, iteration, thread_id, checkpoint_id, checkpoint_ns,
                     anchor_type, timestamp, iteration_status, next_action_summary,
                     tools_executed, reasoning_decision)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (loop_id, iteration, anchor_type)
                    DO UPDATE SET
                        checkpoint_id = EXCLUDED.checkpoint_id,
                        checkpoint_ns = EXCLUDED.checkpoint_ns,
                        timestamp = EXCLUDED.timestamp,
                        iteration_status = EXCLUDED.iteration_status,
                        next_action_summary = EXCLUDED.next_action_summary,
                        tools_executed = EXCLUDED.tools_executed,
                        reasoning_decision = EXCLUDED.reasoning_decision
                """,
                    (
                        loop_id,
                        iteration,
                        thread_id,
                        checkpoint_id,
                        checkpoint_ns,
                        anchor_type,
                        datetime.now(UTC),
                        execution_summary.get("status") if execution_summary else None,
                        execution_summary.get("next_action_summary") if execution_summary else None,
                        json.dumps(execution_summary.get("tools_executed", []))
                        if execution_summary
                        else None,
                        execution_summary.get("reasoning_decision") if execution_summary else None,
                    ),
                )

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
        """Query checkpoint anchors for iteration range.

        Args:
            loop_id: AgentLoop identifier.
            start: Start iteration (inclusive).
            end: End iteration (inclusive).

        Returns:
            List of anchor dicts.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT anchor_id, loop_id, iteration, thread_id, checkpoint_id, checkpoint_ns,
                           anchor_type, timestamp, iteration_status, next_action_summary,
                           tools_executed, reasoning_decision
                    FROM checkpoint_anchors
                    WHERE loop_id = %s AND iteration >= %s AND iteration <= %s
                    ORDER BY iteration ASC, anchor_type ASC
                """,
                    (loop_id, start, end),
                )

                results = await cur.fetchall()
                return results

    async def get_thread_checkpoints_for_loop(
        self, loop_id: str, thread_id: str
    ) -> list[dict[str, Any]]:
        """Query checkpoint anchors for specific thread in loop.

        Args:
            loop_id: AgentLoop identifier.
            thread_id: Thread identifier.

        Returns:
            List of anchor dicts for thread.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT anchor_id, loop_id, iteration, thread_id, checkpoint_id, checkpoint_ns,
                           anchor_type, timestamp, iteration_status, next_action_summary,
                           tools_executed, reasoning_decision
                    FROM checkpoint_anchors
                    WHERE loop_id = %s AND thread_id = %s
                    ORDER BY iteration ASC
                """,
                    (loop_id, thread_id),
                )

                results = await cur.fetchall()
                return results

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
        """Save failed branch record.

        Args:
            branch_id: Branch identifier.
            loop_id: AgentLoop identifier.
            iteration: Iteration where failure occurred.
            thread_id: Thread identifier.
            root_checkpoint_id: Root checkpoint before failure.
            failure_checkpoint_id: Failure checkpoint.
            failure_reason: Failure description.
            execution_path: Execution path leading to failure.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO failed_branches
                    (branch_id, loop_id, iteration, thread_id, root_checkpoint_id,
                     failure_checkpoint_id, failure_reason, execution_path, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        datetime.now(UTC),
                    ),
                )

                logger.debug(
                    "Saved branch: branch=%s loop=%s iter=%d thread=%s",
                    branch_id,
                    loop_id,
                    iteration,
                    thread_id,
                )

    async def update_branch_analysis(
        self,
        branch_id: str,
        loop_id: str,
        failure_insights: dict[str, Any],
        avoid_patterns: list[dict[str, Any]],
        suggested_adjustments: list[dict[str, Any]],
    ) -> None:
        """Update branch analysis insights.

        Args:
            branch_id: Branch identifier.
            loop_id: AgentLoop identifier.
            failure_insights: Failure analysis insights.
            avoid_patterns: Patterns to avoid.
            suggested_adjustments: Suggested strategy adjustments.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE failed_branches
                    SET failure_insights = %s,
                        avoid_patterns = %s,
                        suggested_adjustments = %s,
                        analyzed_at = %s
                    WHERE branch_id = %s AND loop_id = %s
                """,
                    (
                        json.dumps(failure_insights),
                        json.dumps(avoid_patterns),
                        json.dumps(suggested_adjustments),
                        datetime.now(UTC),
                        branch_id,
                        loop_id,
                    ),
                )

                logger.debug("Updated branch: branch=%s loop=%s", branch_id, loop_id)

    async def get_failed_branches_for_loop(
        self, loop_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Query failed branches for loop.

        Args:
            loop_id: AgentLoop identifier.
            limit: Maximum branches to return.

        Returns:
            List of branch dicts.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT branch_id, loop_id, iteration, thread_id, root_checkpoint_id,
                           failure_checkpoint_id, failure_reason, execution_path,
                           failure_insights, avoid_patterns, suggested_adjustments,
                           created_at, analyzed_at, pruned_at
                    FROM failed_branches
                    WHERE loop_id = %s AND pruned_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT %s
                """,
                    (loop_id, limit),
                )

                results = await cur.fetchall()
                return results

    async def prune_old_branches(self, loop_id: str, max_age_days: int = 30) -> int:
        """Prune old failed branches.

        Args:
            loop_id: AgentLoop identifier.
            max_age_days: Maximum age in days.

        Returns:
            Number of branches pruned.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Update pruned_at timestamp for old branches
                await cur.execute(
                    """
                    UPDATE failed_branches
                    SET pruned_at = NOW()
                    WHERE loop_id = %s
                      AND pruned_at IS NULL
                      AND created_at < NOW() - INTERVAL '%s days'
                """,
                    (loop_id, max_age_days),
                )

                # Get count of pruned branches
                count = cur.rowcount
                logger.info(
                    "Pruned %d old branches for loop=%s (max_age=%d days)",
                    count,
                    loop_id,
                    max_age_days,
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
        """Save goal execution record.

        Args:
            goal_id: Goal identifier.
            loop_id: AgentLoop identifier.
            goal_text: Goal description.
            thread_id: Thread identifier.
            iteration: Iteration number.
            status: Goal status.
            started_at: Start timestamp (ISO format).
        """
        pool = await self._ensure_pool()

        # Parse ISO timestamp to datetime
        started_dt = datetime.fromisoformat(started_at)

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO goal_records
                    (goal_id, loop_id, goal_text, thread_id, iteration, status, started_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                    (goal_id, loop_id, goal_text, thread_id, iteration, status, started_dt),
                )

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
        """Update goal execution record.

        Args:
            goal_id: Goal identifier.
            loop_id: AgentLoop identifier.
            status: Goal status.
            goal_completion: Goal completion summary.
            evidence_summary: Evidence summary.
            duration_ms: Duration in milliseconds.
            tokens_used: Tokens consumed.
            completed_at: Completion timestamp (ISO format, None if not completed).
        """
        pool = await self._ensure_pool()

        # Parse ISO timestamp if provided
        completed_dt = datetime.fromisoformat(completed_at) if completed_at else None

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE goal_records
                    SET status = %s,
                        goal_completion = %s,
                        evidence_summary = %s,
                        duration_ms = %s,
                        tokens_used = %s,
                        completed_at = %s
                    WHERE goal_id = %s AND loop_id = %s
                """,
                    (
                        status,
                        goal_completion,
                        evidence_summary,
                        duration_ms,
                        tokens_used,
                        completed_dt,
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
