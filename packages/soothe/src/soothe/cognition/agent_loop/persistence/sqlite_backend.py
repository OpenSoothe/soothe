"""SQLite backend for AgentLoop checkpoint persistence.

RFC-409: AgentLoop Persistence Backend Architecture
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)


class SQLitePersistenceBackend:
    """SQLite backend for AgentLoop checkpoint persistence."""

    SCHEMA_VERSION = "3.1"

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
                    final_report TEXT,
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
                    final_report TEXT,
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
