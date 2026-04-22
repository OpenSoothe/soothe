"""AgentLoop checkpoint persistence manager.

RFC-409: AgentLoop Persistence Backend Architecture

Uses unified global database (loop_checkpoints.db) with loop_id as partition key.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import aiosqlite

from soothe.cognition.agent_loop.persistence.directory_manager import PersistenceDirectoryManager
from soothe.cognition.agent_loop.persistence.sqlite_backend import SQLitePersistenceBackend

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AgentLoopCheckpointPersistenceManager:
    """Manager for AgentLoop checkpoint persistence.

    Uses unified global SQLite database (loop_checkpoints.db) with loop_id as partition key.
    All loop states stored in single database for efficient querying and maintenance.
    """

    def __init__(self, backend: Literal["sqlite", "postgresql"] = "sqlite") -> None:
        """Initialize persistence manager.

        Args:
            backend: Database backend type (default: sqlite).
        """
        self.backend = backend
        # Initialize global database
        self._db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
        SQLitePersistenceBackend.initialize_database_sync(self._db_path)

    async def register_loop(
        self,
        loop_id: str,
        thread_ids: list[str],
        current_thread_id: str,
        status: str = "running",
    ) -> None:
        """Register a new AgentLoop in the database.

        Args:
            loop_id: AgentLoop identifier.
            thread_ids: List of thread IDs associated with this loop.
            current_thread_id: Current active thread ID.
            status: Loop status (default: "running").
        """
        async with self._get_connection() as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
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
            await db.commit()

        logger.debug(
            "Registered loop: loop=%s threads=%s current_thread=%s",
            loop_id,
            thread_ids,
            current_thread_id,
        )

    def _get_connection(self) -> aiosqlite.Connection:
        """Get database connection context manager with FK/WAL pragmas enabled.

        Ensures all operations enforce FK constraints and use WAL mode.
        Creates a fresh connection for each operation to avoid locking conflicts.

        Returns:
            aiosqlite connection context manager with FK/WAL pragmas enabled.
        """
        return aiosqlite.connect(self._db_path)

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
        """Save iteration checkpoint anchor with thread cross-reference.

        Args:
            loop_id: AgentLoop identifier.
            iteration: Iteration number.
            thread_id: Thread where checkpoint belongs (cross-reference).
            checkpoint_id: CoreAgent checkpoint_id.
            anchor_type: "iteration_start", "iteration_end", "failure_point".
            checkpoint_ns: CoreAgent checkpoint namespace.
            execution_summary: Optional execution metadata.
        """
        async with self._get_connection() as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_mode=WAL")
            # Insert anchor
            await db.execute(
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
            await db.commit()

        logger.debug(
            "Saved checkpoint anchor: loop=%s iteration=%d thread=%s checkpoint=%s type=%s",
            loop_id,
            iteration,
            thread_id,
            checkpoint_id,
            anchor_type,
        )

    async def get_checkpoint_anchors_for_range(
        self,
        loop_id: str,
        start_iteration: int,
        end_iteration: int,
    ) -> list[dict[str, Any]]:
        """Get checkpoint anchors for iteration range (failure analysis).

        Args:
            loop_id: AgentLoop identifier.
            start_iteration: Start iteration (inclusive).
            end_iteration: End iteration (inclusive).

        Returns:
            List of checkpoint anchors with metadata.
        """
        if not self._db_path.exists():
            return []

        async with self._get_connection() as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_mode=WAL")
            async with db.execute(
                """
                SELECT iteration, thread_id, checkpoint_id, checkpoint_ns,
                       anchor_type, timestamp, iteration_status,
                       next_action_summary, tools_executed, reasoning_decision
                FROM checkpoint_anchors
                WHERE loop_id = ? AND iteration BETWEEN ? AND ?
                ORDER BY iteration, anchor_type
            """,
                (loop_id, start_iteration, end_iteration),
            ) as cursor:
                rows = await cursor.fetchall()

                return [
                    {
                        "iteration": row[0],
                        "thread_id": row[1],
                        "checkpoint_id": row[2],
                        "checkpoint_ns": row[3],
                        "anchor_type": row[4],
                        "timestamp": row[5],
                        "iteration_status": row[6],
                        "next_action_summary": row[7],
                        "tools_executed": json.loads(row[8]) if row[8] else [],
                        "reasoning_decision": row[9],
                    }
                    for row in rows
                ]

    async def get_thread_checkpoints_for_loop(
        self,
        loop_id: str,
    ) -> dict[str, list[str]]:
        """Get all thread checkpoint_ids for a loop (cross-reference map).

        Args:
            loop_id: AgentLoop identifier.

        Returns:
            Dict: {thread_id: [checkpoint_id_1, checkpoint_id_2, ...]}
        """
        if not self._db_path.exists():
            return {}

        async with self._get_connection() as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_mode=WAL")
            async with db.execute(
                """
                SELECT thread_id, checkpoint_id, iteration, anchor_type
                FROM checkpoint_anchors
                WHERE loop_id = ?
                ORDER BY thread_id, iteration, anchor_type
            """,
                (loop_id,),
            ) as cursor:
                rows = await cursor.fetchall()

                # Group by thread_id
                thread_checkpoints: dict[str, list[str]] = {}
                for row in rows:
                    thread_id = row[0]
                    checkpoint_id = row[1]
                    if thread_id not in thread_checkpoints:
                        thread_checkpoints[thread_id] = []
                    thread_checkpoints[thread_id].append(checkpoint_id)

                return thread_checkpoints

    async def save_failed_branch(
        self,
        branch_id: str,
        loop_id: str,
        iteration: int,
        thread_id: str,
        root_checkpoint_id: str,
        failure_checkpoint_id: str,
        failure_reason: str,
        execution_path: list[str],
    ) -> None:
        """Save failed branch with thread cross-reference.

        Args:
            branch_id: Unique branch identifier.
            loop_id: AgentLoop identifier.
            iteration: Iteration where failure occurred.
            thread_id: Thread where failure occurred (cross-reference).
            root_checkpoint_id: Checkpoint where branch started.
            failure_checkpoint_id: Checkpoint where failure detected.
            failure_reason: High-level failure reason.
            execution_path: List of checkpoint_ids from root → failure.
        """
        async with self._get_connection() as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
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
            await db.commit()

        logger.info(
            "Saved failed branch: branch=%s loop=%s iteration=%d thread=%s reason=%s",
            branch_id,
            loop_id,
            iteration,
            thread_id,
            failure_reason,
        )

    async def update_branch_analysis(
        self,
        branch_id: str,
        loop_id: str,
        failure_insights: dict[str, Any],
        avoid_patterns: list[str],
        suggested_adjustments: list[str],
    ) -> None:
        """Update failed branch with pre-computed learning insights.

        Args:
            branch_id: Branch identifier.
            loop_id: AgentLoop identifier.
            failure_insights: Structured failure analysis.
            avoid_patterns: Patterns to avoid in retry.
            suggested_adjustments: Retry suggestions.
        """
        analyzed_at = datetime.now(UTC)

        async with self._get_connection() as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                """
                UPDATE failed_branches
                SET failure_insights = ?, avoid_patterns = ?,
                    suggested_adjustments = ?, analyzed_at = ?
                WHERE branch_id = ? AND loop_id = ?
            """,
                (
                    json.dumps(failure_insights),
                    json.dumps(avoid_patterns),
                    json.dumps(suggested_adjustments),
                    analyzed_at.isoformat(),
                    branch_id,
                    loop_id,
                ),
            )
            await db.commit()

        logger.info(
            "Updated branch analysis: branch=%s loop=%s patterns=%d adjustments=%d",
            branch_id,
            loop_id,
            len(avoid_patterns),
            len(suggested_adjustments),
        )

    async def get_failed_branches_for_loop(
        self,
        loop_id: str,
        include_pruned: bool = False,
    ) -> list[dict[str, Any]]:
        """Get all failed branches for loop (history reconstruction).

        Args:
            loop_id: AgentLoop identifier.
            include_pruned: Include pruned branches (for audit).

        Returns:
            List of failed branch records.
        """
        if not self._db_path.exists():
            return []

        async with self._get_connection() as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_mode=WAL")
            query = """
                SELECT branch_id, iteration, thread_id, root_checkpoint_id,
                       failure_checkpoint_id, failure_reason, execution_path,
                       failure_insights, avoid_patterns, suggested_adjustments,
                       created_at, analyzed_at, pruned_at
                FROM failed_branches
                WHERE loop_id = ?
            """
            if not include_pruned:
                query += " AND pruned_at IS NULL"

            async with db.execute(query, (loop_id,)) as cursor:
                rows = await cursor.fetchall()

                return [
                    {
                        "branch_id": row[0],
                        "iteration": row[1],
                        "thread_id": row[2],
                        "root_checkpoint_id": row[3],
                        "failure_checkpoint_id": row[4],
                        "failure_reason": row[5],
                        "execution_path": json.loads(row[6]) if row[6] else [],
                        "failure_insights": json.loads(row[7]) if row[7] else {},
                        "avoid_patterns": json.loads(row[8]) if row[8] else [],
                        "suggested_adjustments": json.loads(row[9]) if row[9] else [],
                        "created_at": datetime.fromisoformat(row[10]) if row[10] else None,
                        "analyzed_at": datetime.fromisoformat(row[11]) if row[11] else None,
                        "pruned_at": datetime.fromisoformat(row[12]) if row[12] else None,
                    }
                    for row in rows
                ]

    async def prune_old_branches(
        self,
        loop_id: str,
        retention_days: int = 30,
    ) -> int:
        """Prune old branches (soft delete with pruned_at timestamp).

        Args:
            loop_id: AgentLoop identifier.
            retention_days: Keep branches created within this period.

        Returns:
            Number of branches pruned.
        """
        from datetime import timedelta

        threshold = datetime.now(UTC) - timedelta(days=retention_days)

        if not self._db_path.exists():
            return 0

        async with self._get_connection() as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                """
                UPDATE failed_branches
                SET pruned_at = ?
                WHERE loop_id = ? AND created_at < ? AND pruned_at IS NULL
            """,
                (datetime.now(UTC).isoformat(), loop_id, threshold.isoformat()),
            )
            await db.commit()

            # Count pruned branches
            async with db.execute(
                """
                SELECT COUNT(*) FROM failed_branches
                WHERE loop_id = ? AND pruned_at = ?
            """,
                (loop_id, datetime.now(UTC).isoformat()),
            ) as cursor:
                count_row = await cursor.fetchone()
                count = count_row[0] if count_row else 0

        logger.info(
            "Pruned %d old branches for loop=%s (retention=%d days)",
            count,
            loop_id,
            retention_days,
        )

        return count

    async def save_goal_record(
        self,
        goal_id: str,
        loop_id: str,
        thread_id: str,
        goal_text: str,
        iteration: int = 0,
        status: str = "running",
        started_at: datetime | None = None,
    ) -> None:
        """Save goal execution record to SQLite goal_records table (RFC-409).

        Args:
            goal_id: Goal identifier.
            loop_id: AgentLoop identifier.
            thread_id: Thread where goal executes.
            goal_text: Goal description.
            iteration: Current iteration number.
            status: Goal status ("running", "completed", "failed").
            started_at: Goal start timestamp.
        """
        started_at_iso = (started_at or datetime.now(UTC)).isoformat()

        async with self._get_connection() as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                """
                INSERT OR REPLACE INTO goal_records
                (goal_id, loop_id, goal_text, thread_id, iteration, status, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (goal_id, loop_id, goal_text, thread_id, iteration, status, started_at_iso),
            )
            await db.commit()

        logger.debug(
            "Saved goal record: goal=%s loop=%s thread=%s status=%s",
            goal_id,
            loop_id,
            thread_id,
            status,
        )

    async def update_goal_record(
        self,
        goal_id: str,
        loop_id: str,
        status: str = "completed",
        final_report: str = "",
        evidence_summary: str = "",
        iteration: int = 0,
        duration_ms: int = 0,
        tokens_used: int = 0,
        completed_at: datetime | None = None,
    ) -> None:
        """Update goal record with execution results (RFC-409).

        Args:
            goal_id: Goal identifier.
            loop_id: AgentLoop identifier.
            status: Final goal status.
            final_report: Generated final report content.
            evidence_summary: Condensed evidence summary.
            iteration: Final iteration number.
            duration_ms: Goal execution duration.
            tokens_used: Tokens consumed.
            completed_at: Goal completion timestamp.
        """
        if not self._db_path.exists():
            logger.warning("Goal record database not found: %s", self._db_path)
            return

        completed_at_iso = (completed_at or datetime.now(UTC)).isoformat()

        async with self._get_connection() as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                """
                UPDATE goal_records
                SET status = ?, iteration = ?, final_report = ?, evidence_summary = ?,
                    duration_ms = ?, tokens_used = ?, completed_at = ?
                WHERE goal_id = ? AND loop_id = ?
            """,
                (
                    status,
                    iteration,
                    final_report,
                    evidence_summary,
                    duration_ms,
                    tokens_used,
                    completed_at_iso,
                    goal_id,
                    loop_id,
                ),
            )
            await db.commit()

        logger.info(
            "Updated goal record: goal=%s loop=%s status=%s duration=%dms tokens=%d",
            goal_id,
            loop_id,
            status,
            duration_ms,
            tokens_used,
        )

    def write_goal_report_markdown(
        self,
        loop_id: str,
        goal_id: str,
        description: str,
        summary: str,
        status: str,
        duration_ms: int,
        reflection_assessment: str = "",
        cross_validation_notes: str = "",
        step_reports: list[Any] | None = None,
    ) -> None:
        """Write goal report markdown file at loop level (RFC-409).

        Path: data/loops/{loop_id}/goals/{goal_id}/report.md

        Args:
            loop_id: AgentLoop identifier.
            goal_id: Goal identifier.
            description: Goal description.
            summary: Goal summary.
            status: Goal status.
            duration_ms: Execution duration in milliseconds.
            reflection_assessment: Reflection analysis text.
            cross_validation_notes: Cross-validation notes.
            step_reports: List of step report objects.
        """
        goal_dir = PersistenceDirectoryManager.get_goal_directory(loop_id, goal_id)
        goal_dir.mkdir(parents=True, exist_ok=True)

        # Build Markdown report
        md_parts = [
            f"# Goal: {description}\n",
            f"**Status**: {status}  \n**Duration**: {duration_ms}ms\n",
            f"\n## Summary\n\n{summary}\n",
        ]
        if reflection_assessment:
            md_parts.append(f"\n## Reflection\n\n{reflection_assessment}\n")
        if cross_validation_notes:
            md_parts.append(f"\n## Cross-Validation\n\n{cross_validation_notes}\n")

        step_reports_list = step_reports or []
        if step_reports_list:
            md_parts.append("\n## Steps\n")
            for sr in step_reports_list:
                icon = "+" if getattr(sr, "status", "") == "completed" else "x"
                step_id = getattr(sr, "step_id", "unknown")
                step_desc = getattr(sr, "description", "")
                step_status = getattr(sr, "status", "")
                md_parts.append(f"- [{icon}] **{step_id}**: {step_desc} ({step_status})")
            md_parts.append("")

        md_path = goal_dir / "report.md"
        md_path.write_text("\n".join(md_parts), encoding="utf-8")

        logger.info(
            "Wrote goal report markdown: goal=%s loop=%s path=%s",
            goal_id,
            loop_id,
            md_path,
        )

    def write_step_report_markdown(
        self,
        loop_id: str,
        goal_id: str,
        step_id: str,
        description: str,
        status: str,
        result: str,
        duration_ms: int,
        depends_on: list[str] | None = None,
    ) -> None:
        """Write step report markdown file at loop level (RFC-409).

        Path: data/loops/{loop_id}/goals/{goal_id}/steps/{step_id}/report.md

        Args:
            loop_id: AgentLoop identifier.
            goal_id: Goal identifier.
            step_id: Step identifier.
            description: Step description.
            status: Step status.
            result: Step execution result.
            duration_ms: Execution duration in milliseconds.
            depends_on: Step dependency IDs.
        """
        step_dir = PersistenceDirectoryManager.get_step_directory(loop_id, goal_id, step_id)
        step_dir.mkdir(parents=True, exist_ok=True)

        deps = depends_on or []

        # Build Markdown report
        md_parts = [
            f"# Step: {description}\n",
            f"**Status**: {status}  \n**Duration**: {duration_ms}ms\n",
        ]
        if deps:
            md_parts.append(f"**Depends on**: {', '.join(deps)}\n")
        md_parts.append(f"\n## Result\n\n{result}\n")

        md_path = step_dir / "report.md"
        md_path.write_text("\n".join(md_parts), encoding="utf-8")

        logger.debug(
            "Wrote step report markdown: step=%s goal=%s loop=%s path=%s",
            step_id,
            goal_id,
            loop_id,
            md_path,
        )


__all__ = ["AgentLoopCheckpointPersistenceManager"]
