"""AgentLoop checkpoint persistence manager.

RFC-409: AgentLoop Persistence Backend Architecture
IG-055: Backend-agnostic delegation pattern supporting PostgreSQL and SQLite
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe.cognition.agent_loop.persistence.directory_manager import PersistenceDirectoryManager
from soothe.cognition.agent_loop.persistence.postgres_backend import PostgreSQLPersistenceBackend
from soothe.cognition.agent_loop.persistence.sqlite_backend import SQLitePersistenceBackend

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class AgentLoopCheckpointPersistenceManager:
    """Manager for AgentLoop checkpoint persistence.

    IG-055: Backend-agnostic delegation pattern.
    Respects persistence.default_backend configuration (PostgreSQL or SQLite).
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        """Initialize persistence manager with backend selection.

        Args:
            config: SootheConfig for backend selection.
                    If None, defaults to SQLite (backward compatibility).
        """
        # Determine backend type
        backend_type = "sqlite"  # Default for backward compatibility
        if config and config.persistence.default_backend == "postgresql":
            backend_type = "postgresql"

        # Initialize backend instance
        if backend_type == "postgresql":
            dsn = config.resolve_postgres_dsn_for_database("checkpoints")
            self._backend = PostgreSQLPersistenceBackend(dsn=dsn, pool_size=10)
        else:
            db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
            self._backend = SQLitePersistenceBackend(db_path=db_path, pool_size=5)

        logger.info("AgentLoop persistence manager initialized: backend=%s", backend_type)

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
        await self._backend.register_loop(loop_id, thread_ids, current_thread_id, status)
        logger.debug(
            "Registered loop: loop=%s threads=%s current_thread=%s",
            loop_id,
            thread_ids,
            current_thread_id,
        )

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
        await self._backend.save_checkpoint_anchor(
            loop_id,
            iteration,
            thread_id,
            checkpoint_id,
            anchor_type,
            checkpoint_ns,
            execution_summary,
        )
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
        return await self._backend.get_checkpoint_anchors_for_range(
            loop_id, start_iteration, end_iteration
        )

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
        # Query anchors grouped by thread_id
        anchors = await self._backend.get_thread_checkpoints_for_loop(loop_id, thread_id=None)

        # Group by thread_id
        thread_checkpoints: dict[str, list[str]] = {}
        for anchor in anchors:
            thread_id = anchor["thread_id"]
            checkpoint_id = anchor["checkpoint_id"]
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
        await self._backend.save_failed_branch(
            branch_id,
            loop_id,
            iteration,
            thread_id,
            root_checkpoint_id,
            failure_checkpoint_id,
            failure_reason,
            execution_path,
        )
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
        await self._backend.update_branch_analysis(
            branch_id, loop_id, failure_insights, avoid_patterns, suggested_adjustments
        )
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
        # Backend returns all non-pruned by default
        branches = await self._backend.get_failed_branches_for_loop(loop_id)

        # Filter pruned if requested
        if not include_pruned:
            branches = [b for b in branches if b.get("pruned_at") is None]

        return branches

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
        count = await self._backend.prune_old_branches(loop_id, retention_days)
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
        """Save goal execution record (RFC-409).

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
        await self._backend.save_goal_record(
            goal_id, loop_id, goal_text, thread_id, iteration, status, started_at_iso
        )
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
        goal_completion: str = "",
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
            goal_completion: Generated goal completion content.
            evidence_summary: Condensed evidence summary.
            iteration: Final iteration number.
            duration_ms: Goal execution duration.
            tokens_used: Tokens consumed.
            completed_at: Goal completion timestamp.
        """
        completed_at_iso = (completed_at or datetime.now(UTC)).isoformat()
        await self._backend.update_goal_record(
            goal_id,
            loop_id,
            status,
            goal_completion,
            evidence_summary,
            duration_ms,
            tokens_used,
            completed_at_iso,
        )
        logger.debug(
            "Updated goal record: goal=%s loop=%s status=%s duration=%dms",
            goal_id,
            loop_id,
            status,
            duration_ms,
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
