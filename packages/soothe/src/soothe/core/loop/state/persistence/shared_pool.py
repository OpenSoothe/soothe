"""Shared PostgreSQL connection pool for AgentLoop persistence (IG-406).

Provides a singleton pool at daemon level for high-concurrency scenarios
(200+ threads). Each AgentLoopStateManager reuses this shared pool instead
of creating its own, preventing connection exhaustion.

Architecture:
    Daemon → SootheRunner → SharedPostgreSQLPool
                      ↓
    AgentLoopStateManager (receives pool reference)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

# Singleton instance for daemon-level shared pool
_shared_pool: SharedPostgreSQLPool | None = None
_pool_lock = asyncio.Lock()


class SharedPostgreSQLPool:
    """Shared PostgreSQL connection pool for AgentLoop state persistence.

    IG-406: High-concurrency architecture with 200+ thread support.
    Pool size is config-driven (``persistence.agentloop_pool_size``); default suits
    one active run per process (e.g. pool workers) without multiplying connections by 30×N workers.

    Usage:
        # Initialize at daemon startup
        pool = SharedPostgreSQLPool(dsn, pool_size=12)
        await pool.open()

        # Pass to AgentLoopStateManager
        state_manager = AgentLoopStateManager(config=config, shared_pool=pool)

        # Close at daemon shutdown
        await pool.close()
    """

    def __init__(self, dsn: str, pool_size: int = 12) -> None:
        """Initialize shared pool configuration.

        Args:
            dsn: PostgreSQL DSN for soothe_checkpoints database.
            pool_size: Shared pool ``max_size`` (default matches ``PersistenceConfig``).
        """
        self.dsn = dsn
        self.pool_size = pool_size
        self._pool: AsyncConnectionPool | None = None
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def open(self) -> AsyncConnectionPool:
        """Open the shared connection pool with schema initialization.

        Returns:
            Opened AsyncConnectionPool instance.
        """
        if self._pool is not None and self._initialized:
            return self._pool

        async with self._init_lock:
            if self._pool is not None and self._initialized:
                return self._pool

            # Create connection pool (min_size=1: avoid psycopg default min_size=4 when max is small)
            self._pool = AsyncConnectionPool(
                self.dsn,
                min_size=1,
                max_size=self.pool_size,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
                open=False,
            )

            # Open pool
            await self._pool.open()

            # Initialize schema (agentloop_checkpoints, checkpoint_anchors, etc.)
            await self._initialize_schema(self._pool)

            self._initialized = True
            logger.info(
                "Shared PostgreSQL pool opened for AgentLoop persistence (size=%d, DSN masked)",
                self.pool_size,
            )

            return self._pool

    async def _initialize_schema(self, pool: AsyncConnectionPool) -> None:
        """Create AgentLoop checkpoint tables if not exist.

        Schema matches PostgreSQLPersistenceBackend._initialize_schema()
        for compatibility with existing backend operations.

        Args:
            pool: Connection pool to use for schema creation.
        """
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Create agentloop_checkpoints table
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

                # Create indexes
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

                # Create checkpoint_anchors table
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

                # Create indexes for checkpoint_anchors
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

                # Create failed_branches table
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

                # Create indexes for failed_branches
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

                # Create goal_records table
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

                # Create indexes for goal_records
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_goals_loop
                    ON goal_records(loop_id)
                """)
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_goals_thread
                    ON goal_records(thread_id)
                """)

                logger.info(
                    "Shared PostgreSQL schema initialized (4 tables: checkpoints, anchors, branches, goals)"
                )

    async def close(self) -> None:
        """Close the shared connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            self._initialized = False
            logger.info("Shared PostgreSQL pool closed")

    def get_pool(self) -> AsyncConnectionPool | None:
        """Get the underlying pool instance (for direct access).

        Returns:
            AsyncConnectionPool if initialized, None otherwise.
        """
        return self._pool

    @classmethod
    async def get_shared_instance(cls, config: SootheConfig) -> SharedPostgreSQLPool | None:
        """Get or create the singleton shared pool instance.

        IG-406: Daemon-level singleton for high-concurrency support.
        Creates pool only if PostgreSQL backend is configured.

        Args:
            config: SootheConfig for backend detection and DSN resolution.

        Returns:
            SharedPostgreSQLPool instance if PostgreSQL configured, None for SQLite.
        """
        global _shared_pool

        if config.persistence.default_backend != "postgresql":
            return None

        async with _pool_lock:
            if _shared_pool is None:
                dsn = config.resolve_postgres_dsn_for_database("checkpoints")
                pool_size = config.persistence.agentloop_pool_size
                _shared_pool = SharedPostgreSQLPool(dsn, pool_size=pool_size)
                await _shared_pool.open()
                logger.info("Created singleton shared PostgreSQL pool (size=%d)", pool_size)

            return _shared_pool

    @classmethod
    async def close_shared_instance(cls) -> None:
        """Close the singleton shared pool (daemon shutdown)."""
        global _shared_pool

        async with _pool_lock:
            if _shared_pool is not None:
                await _shared_pool.close()
                _shared_pool = None


__all__ = ["SharedPostgreSQLPool"]
