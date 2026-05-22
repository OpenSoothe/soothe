"""Canonical PostgreSQL schema for AgentLoop persistence.

Clean-cut initialization: existing AgentLoop tables are dropped and recreated
on pool open. No incremental migration of legacy schemas.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

_AGENTLOOP_TABLES_DROP_ORDER = (
    "goal_records",
    "failed_branches",
    "checkpoint_anchors",
    "agentloop_checkpoints",
)


async def initialize_agentloop_postgres_schema(pool: AsyncConnectionPool) -> None:
    """Drop and recreate AgentLoop persistence tables with the current schema.

    Args:
        pool: Open ``AsyncConnectionPool`` for the soothe_checkpoints database.
    """
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            for table in _AGENTLOOP_TABLES_DROP_ORDER:
                await cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")  # noqa: S608

            await cur.execute("""
                CREATE TABLE agentloop_checkpoints (
                    loop_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    checkpoint_data JSONB NOT NULL,
                    client_workspace TEXT,
                    detached_at TIMESTAMPTZ,
                    user_id TEXT
                )
            """)

            await cur.execute("""
                CREATE INDEX idx_agentloop_checkpoints_thread_id
                ON agentloop_checkpoints(thread_id)
            """)
            await cur.execute("""
                CREATE INDEX idx_agentloop_checkpoints_status
                ON agentloop_checkpoints(status)
            """)
            await cur.execute("""
                CREATE INDEX idx_agentloop_checkpoints_updated_at
                ON agentloop_checkpoints(updated_at DESC)
            """)

            await cur.execute("""
                CREATE TABLE checkpoint_anchors (
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
            await cur.execute("""
                CREATE INDEX idx_anchors_loop_iteration
                ON checkpoint_anchors(loop_id, iteration)
            """)
            await cur.execute("""
                CREATE INDEX idx_anchors_thread
                ON checkpoint_anchors(thread_id)
            """)
            await cur.execute("""
                CREATE INDEX idx_anchors_loop_thread
                ON checkpoint_anchors(loop_id, thread_id)
            """)

            await cur.execute("""
                CREATE TABLE failed_branches (
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
            await cur.execute("""
                CREATE INDEX idx_branches_loop ON failed_branches(loop_id)
            """)
            await cur.execute("""
                CREATE INDEX idx_branches_thread ON failed_branches(thread_id)
            """)
            await cur.execute("""
                CREATE INDEX idx_branches_iteration
                ON failed_branches(loop_id, iteration)
            """)

            await cur.execute("""
                CREATE TABLE goal_records (
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
            await cur.execute("""
                CREATE INDEX idx_goals_loop ON goal_records(loop_id)
            """)
            await cur.execute("""
                CREATE INDEX idx_goals_thread ON goal_records(thread_id)
            """)

    logger.info(
        "AgentLoop PostgreSQL schema initialized (4 tables: checkpoints, anchors, branches, goals)"
    )


__all__ = ["initialize_agentloop_postgres_schema"]
