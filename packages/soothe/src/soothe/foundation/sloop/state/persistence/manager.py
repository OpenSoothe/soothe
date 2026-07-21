"""StrangeLoop checkpoint persistence manager.

RFC-215: StrangeLoop Persistence Backend Architecture
IG-055: Backend-agnostic delegation pattern supporting PostgreSQL and SQLite
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe.foundation.sloop.state.persistence.directory_manager import (
    PersistenceDirectoryManager,
)
from soothe.foundation.sloop.state.persistence.shared_pool import (
    acquire_shared_sqlite_backend_sync,
    release_shared_sqlite_backend,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class StrangeLoopCheckpointPersistenceManager:
    """Manager for StrangeLoop checkpoint persistence.

    IG-055: Backend-agnostic delegation pattern.
    Respects persistence.default_backend configuration (PostgreSQL or SQLite).
    """

    def __init__(
        self,
        config: SootheConfig | None = None,
        *,
        display_loop_purger: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize persistence manager with backend selection.

        Args:
            config: SootheConfig for backend selection. If None, uses SQLite.
            display_loop_purger: Optional callable that purges a loop's display
                card data (``delete_loop(loop_id)``). Injected by the daemon,
                which owns the display card store (IG-678 PR-2). No-op when None
                (keeps the host free of daemon imports).
        """
        self._display_loop_purger = display_loop_purger
        # Determine backend type
        backend_type = "sqlite"
        if config and config.persistence.default_backend == "postgresql":
            backend_type = "postgresql"

        # Initialize backend instance
        self._uses_shared_sqlite = False
        self._uses_shared_postgres = False
        if backend_type == "postgresql":
            try:
                from soothe.foundation.persistence.postgres_pool_lifecycle import (
                    postgres_pool_timing_from_config,
                )
                from soothe.foundation.sloop.state.persistence.postgres_backend import (
                    PostgreSQLPersistenceBackend,
                )
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "PostgreSQL persistence backend requires `psycopg`. "
                    "Install with: pip install -U soothe"
                ) from exc
            dsn = config.resolve_postgres_dsn_for_database("checkpoints")
            pool_size = config.persistence.metadata_pool_size
            pool_timing = postgres_pool_timing_from_config(config, max_size=pool_size)
            self._backend = PostgreSQLPersistenceBackend(
                dsn=dsn,
                pool_size=pool_size,
                pool_timing=pool_timing,
            )
        else:
            self._backend = acquire_shared_sqlite_backend_sync()
            self._uses_shared_sqlite = True

        logger.debug("StrangeLoop persistence manager initialized: backend=%s", backend_type)

    @classmethod
    async def for_shared_checkpoint_pool(
        cls,
        config: SootheConfig,
        *,
        display_loop_purger: Callable[[str], None] | None = None,
    ) -> StrangeLoopCheckpointPersistenceManager:
        """Build a manager backed by the process-wide checkpoint pool.

        Ephemeral callers (heartbeat ticks, deferred counters, resume topic)
        must use this instead of constructing an owned ``AsyncConnectionPool``
        per call.
        """
        if config.persistence.default_backend != "postgresql":
            return cls(config=config, display_loop_purger=display_loop_purger)

        from soothe.foundation.sloop.state.persistence.postgres_backend import (
            PostgreSQLPersistenceBackend,
        )
        from soothe.foundation.sloop.state.persistence.shared_pool import (
            SharedPostgreSQLPool,
        )

        shared = await SharedPostgreSQLPool.get_shared_instance(config)
        if shared is None:
            return cls(config=config)

        pool = shared.get_pool()
        if pool is None:
            msg = "Shared checkpoint pool not initialized"
            raise RuntimeError(msg)

        dsn = config.resolve_postgres_dsn_for_database("checkpoints")
        manager = cls.__new__(cls)
        manager._uses_shared_sqlite = False
        manager._uses_shared_postgres = True
        manager._display_loop_purger = display_loop_purger
        manager._backend = PostgreSQLPersistenceBackend(
            dsn=dsn,
            pool_size=0,
            shared_pool=shared,
        )
        manager._backend._pool = pool
        return manager

    async def register_loop(
        self,
        loop_id: str,
        thread_ids: list[str],
        current_thread_id: str,
        status: str = "running",
    ) -> None:
        """Register a new StrangeLoop in the database.

        Args:
            loop_id: StrangeLoop identifier.
            thread_ids: List of thread IDs associated with this loop.
            current_thread_id: Current active thread ID.
            status: Loop status (default: "running").
        """
        await self._backend.register_loop(loop_id, thread_ids, current_thread_id, status)
        logger.debug(
            "Registered loop: loop=%s threads=%s current=%s", loop_id, thread_ids, current_thread_id
        )

    async def get_loop_metadata(self, loop_id: str) -> dict | None:
        """Get loop metadata from database.

        Args:
            loop_id: Loop identifier.

        Returns:
            Loop metadata dict if found, None otherwise.
        """
        return await self._backend.get_loop_metadata(loop_id)

    async def update_loop_metadata(self, loop_id: str, **fields: Any) -> None:
        """Partially update loop metadata fields.

        Args:
            loop_id: Loop identifier.
            **fields: Column names and values to update.
        """
        await self._backend.update_loop_metadata(loop_id, **fields)

    async def set_resume_topic_once(self, loop_id: str, topic: str) -> bool:
        """Persist resume topic only when the loop has no stored topic yet.

        Args:
            loop_id: Loop identifier.
            topic: Generated topic label.

        Returns:
            True when the topic was written, False when one already existed.
        """
        setter = getattr(self._backend, "set_resume_topic_once", None)
        if setter is None:
            metadata = await self.get_loop_metadata(loop_id)
            existing = (metadata or {}).get("resume_topic")
            if isinstance(existing, str) and existing.strip():
                return False
            await self.update_loop_metadata(loop_id, resume_topic=topic.strip())
            return True
        return await setter(loop_id, topic)

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

        Returns:
            List of loop metadata dicts.
        """
        return await self._backend.list_loops(
            status_filter=status_filter,
            limit=limit,
            exclude_empty=exclude_empty,
            workspace_filter=workspace_filter,
        )

    async def touch_loop_last_message(self, loop_id: str) -> None:
        """Record user turn activity for ephemeral loop TTL."""
        await self._backend.touch_loop_last_message(loop_id)

    async def heartbeat_loop(self, loop_id: str) -> None:
        """Bump ``updated_at`` for periodic status reconciliation."""
        await self._backend.heartbeat_loop(loop_id)

    async def increment_loop_message_count(
        self,
        loop_id: str,
        human: int = 0,
        ai: int = 0,
    ) -> None:
        """Atomically bump human/AI message counters and refresh activity timestamp."""
        await self._backend.increment_loop_message_count(loop_id, human=human, ai=ai)

    async def list_expired_ephemeral_loops(
        self,
        idle_before: datetime,
        limit: int = 50,
    ) -> list[dict]:
        """Return ephemeral loops idle since ``idle_before`` (excludes running)."""
        return await self._backend.list_expired_ephemeral_loops(idle_before, limit)

    async def list_empty_loops(
        self,
        idle_before: datetime,
        limit: int = 50,
    ) -> list[dict]:
        """Return loops with zero human/AI messages idle since ``idle_before``."""
        return await self._backend.list_empty_loops(idle_before, limit)

    async def purge_loop_execution_data(self, loop_id: str) -> None:
        """Delete loop row and related execution tables (keeps workspace dirs)."""
        import asyncio

        from soothe.foundation.context.persistence.sqlite_backend import (
            purge_loop_context_engine_state,
        )

        await self._backend.purge_loop_execution_data(loop_id)
        if self._display_loop_purger is not None:
            await asyncio.to_thread(self._display_loop_purger, loop_id)
        await asyncio.to_thread(purge_loop_context_engine_state, loop_id)
        logger.info("Purged loop execution data: loop=%s", loop_id)

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
            loop_id: StrangeLoop identifier.
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
            "Saved anchor: loop=%s iter=%d thread=%s checkpoint=%s type=%s",
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
            loop_id: StrangeLoop identifier.
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
            loop_id: StrangeLoop identifier.

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
            loop_id: StrangeLoop identifier.
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
            loop_id: StrangeLoop identifier.
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
            loop_id: StrangeLoop identifier.
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
            loop_id: StrangeLoop identifier.
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
        status: str = "running",
        started_at: datetime | None = None,
    ) -> None:
        """Save goal index entry (RFC-626)."""
        started_at_iso = (started_at or datetime.now(UTC)).isoformat()
        await self._backend.save_goal_record(goal_id, loop_id, thread_id, status, started_at_iso)
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
        status: str = "completed",
        duration_ms: int = 0,
        tokens_used: int = 0,
        completed_at: datetime | None = None,
    ) -> None:
        """Update goal index entry with execution metrics (RFC-626)."""
        completed_at_iso = (completed_at or datetime.now(UTC)).isoformat()
        await self._backend.update_goal_record(
            goal_id,
            loop_id,
            status,
            duration_ms,
            tokens_used,
            completed_at_iso,
        )
        logger.debug(
            "Updated goal: id=%s loop=%s status=%s dur=%dms",
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
        """Write goal report markdown file at loop level (RFC-215).

        Path: data/loops/{loop_id}/goals/{goal_id}/report.md

        Args:
            loop_id: StrangeLoop identifier.
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
        """Write step report markdown file at loop level (RFC-215).

        Path: data/loops/{loop_id}/goals/{goal_id}/steps/{step_id}/report.md

        Args:
            loop_id: StrangeLoop identifier.
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
            "Wrote step report: step=%s goal=%s loop=%s path=%s",
            step_id,
            goal_id,
            loop_id,
            md_path,
        )

    async def close(self) -> None:
        """Close backend connection pools (IG-404: prevent pool exhaustion).

        Must be called when manager is no longer needed to release database connections.
        Critical for concurrent execution where multiple managers may exist.
        """
        if self._uses_shared_sqlite:
            await release_shared_sqlite_backend()
            logger.debug("Released shared SQLite persistence backend reference")
            return
        if self._uses_shared_postgres:
            self._backend = None
            logger.debug("Released shared PostgreSQL persistence backend reference")
            return
        if hasattr(self._backend, "close"):
            await self._backend.close()
            logger.debug("Closed persistence backend pool")


__all__ = ["StrangeLoopCheckpointPersistenceManager"]
