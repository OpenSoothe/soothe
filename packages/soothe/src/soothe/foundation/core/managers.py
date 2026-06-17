"""Core managers module (RFC-228, RFC-626).

This module provides manager classes for job lifecycle operations:
- JobManager: Manages job lifecycle transitions and checkpoint persistence
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.foundation.context.models import GoalNode
from soothe.foundation.core.entities import (
    JOB_TERMINAL_STATES,
    Job,
    JobCheckpoint,
    JobState,
)

if TYPE_CHECKING:
    from soothe.foundation.context.engine import ContextEngine
    from soothe.protocols.persistence import AsyncPersistStore

logger = logging.getLogger(__name__)

_KEY_PREFIX = "autopilot:job_checkpoint:"


class JobManager:
    """Manage job lifecycle transitions and checkpoint persistence (RFC-228, RFC-626).

    JobManager provides lifecycle operations for root GoalNodes (jobs):
    - Create: Submit new job to ContextEngine, persist checkpoint
    - Pause: Transition job to suspended state, update checkpoint
    - Resume: Transition job from suspended to pending/active, update checkpoint
    - Cancel: Transition job to cancelled state, cleanup checkpoint
    - Status: Query job state and metrics from ContextEngine

    JobManager uses AsyncPersistStore for checkpoint durability, enabling
    job state recovery across daemon restarts (RFC-222 H4).

    Args:
        ce: ContextEngine instance for goal management.
        persist_store: Optional AsyncPersistStore for checkpoint persistence.
            When None, checkpoints are not persisted (suitable for transient jobs).
    """

    def __init__(
        self,
        ce: ContextEngine,
        persist_store: AsyncPersistStore | None = None,
    ) -> None:
        """Initialize JobManager.

        Args:
            ce: ContextEngine instance for goal management.
            persist_store: Optional AsyncPersistStore for checkpoint persistence.
        """
        self._ce = ce
        self._persist_store = persist_store

    def _checkpoint_key(self, job_id: str) -> str:
        """Generate persistence key for job checkpoint.

        Args:
            job_id: Job identifier (8-char hex).

        Returns:
            Persistence key string.
        """
        return f"{_KEY_PREFIX}{job_id}"

    # ── Lifecycle Operations ─────────────────────────────────────────────

    async def create_job(
        self,
        description: str,
        *,
        priority: int = 50,
        workspace: str | None = None,
        source_file: str | None = None,
    ) -> Job:
        """Create a new job (root goal) and persist initial checkpoint.

        Args:
            description: Job goal description text.
            priority: Job priority (0-100, higher = more urgent).
            workspace: Optional workspace path for execution.
            source_file: Optional source GOAL.md file path.

        Returns:
            Newly created Job entity.

        Raises:
            ValueError: If goal creation fails or depth limit exceeded.
        """
        goal = await self._ce.create_goal(
            description,
            priority=priority,
            parent_id=None,  # Root goal = Job
            workspace=workspace,
            source_file=source_file,
        )

        job = self._goal_to_job(goal)
        checkpoint = self._build_checkpoint(job)

        await self._persist_checkpoint(job.id, checkpoint)
        logger.info("Created job %s: %s", job.id, description[:80])
        return job

    async def pause_job(self, job_id: str, *, reason: str = "user_request") -> Job | None:
        """Pause a job by transitioning to suspended state.

        Args:
            job_id: Job identifier to pause.
            reason: Reason for suspension (for audit trail).

        Returns:
            Updated Job entity if found and paused, None if job not found.

        Raises:
            ValueError: If job is in terminal state or already suspended.
        """
        goal = await self._ce.get_goal(job_id)
        if goal is None:
            logger.warning("pause_job: job %s not found", job_id)
            return None

        job = self._goal_to_job(goal)

        # Validate transition
        if job.state in JOB_TERMINAL_STATES:
            raise ValueError(f"Cannot pause job {job_id}: terminal state {job.state}")
        if job.state == JobState.SUSPENDED:
            raise ValueError(f"Job {job_id} already suspended")

        # Transition via ContextEngine
        await self._ce.suspend_goal(job_id, reason=reason)

        # Fetch updated state and persist checkpoint
        updated_goal = await self._ce.get_goal(job_id)
        if updated_goal is None:
            return None

        updated_job = self._goal_to_job(updated_goal)
        checkpoint = self._build_checkpoint(updated_job)
        await self._persist_checkpoint(job_id, checkpoint)

        logger.info("Paused job %s: reason=%s", job_id, reason)
        return updated_job

    async def resume_job(self, job_id: str) -> Job | None:
        """Resume a suspended job by transitioning to pending state.

        Args:
            job_id: Job identifier to resume.

        Returns:
            Updated Job entity if found and resumed, None if job not found.

        Raises:
            ValueError: If job is not in suspended state or is terminal.
        """
        goal = await self._ce.get_goal(job_id)
        if goal is None:
            logger.warning("resume_job: job %s not found", job_id)
            return None

        job = self._goal_to_job(goal)

        # Validate transition
        if job.state in JOB_TERMINAL_STATES:
            raise ValueError(f"Cannot resume job {job_id}: terminal state {job.state}")
        if job.state != JobState.SUSPENDED:
            raise ValueError(f"Job {job_id} not suspended (state={job.state})")

        # Transition via ContextEngine
        await self._ce.reactivate_goal(job_id)

        # Fetch updated state and persist checkpoint
        updated_goal = await self._ce.get_goal(job_id)
        if updated_goal is None:
            return None

        updated_job = self._goal_to_job(updated_goal)
        checkpoint = self._build_checkpoint(updated_job)
        await self._persist_checkpoint(job_id, checkpoint)

        logger.info("Resumed job %s", job_id)
        return updated_job

    async def cancel_job(self, job_id: str, *, reason: str = "user_cancelled") -> Job | None:
        """Cancel a job by transitioning to cancelled state.

        Args:
            job_id: Job identifier to cancel.
            reason: Reason for cancellation (for audit trail).

        Returns:
            Updated Job entity if found and cancelled, None if job not found.

        Raises:
            ValueError: If job is already in terminal state.
        """
        goal = await self._ce.get_goal(job_id)
        if goal is None:
            logger.warning("cancel_job: job %s not found", job_id)
            return None

        job = self._goal_to_job(goal)

        # Validate transition
        if job.state in JOB_TERMINAL_STATES:
            raise ValueError(f"Cannot cancel job {job_id}: terminal state {job.state}")

        # Transition via ContextEngine
        await self._ce.cancel_goal(job_id, reason=reason)

        # Fetch updated state and persist checkpoint
        updated_goal = await self._ce.get_goal(job_id)
        if updated_goal is None:
            return None

        updated_job = self._goal_to_job(updated_goal)
        checkpoint = self._build_checkpoint(updated_job)
        await self._persist_checkpoint(job_id, checkpoint)

        logger.info("Cancelled job %s: reason=%s", job_id, reason)
        return updated_job

    # ── Status Queries ────────────────────────────────────────────────────

    async def get_job(self, job_id: str) -> Job | None:
        """Get job entity by identifier.

        Args:
            job_id: Job identifier to query.

        Returns:
            Job entity if found, None if not found.
        """
        goal = await self._ce.get_goal(job_id)
        if goal is None:
            return None
        return self._goal_to_job(goal)

    async def get_job_checkpoint(self, job_id: str) -> JobCheckpoint | None:
        """Get job checkpoint from persistence.

        Args:
            job_id: Job identifier to query.

        Returns:
            JobCheckpoint if found in persistence, None if not found.
        """
        if self._persist_store is None:
            # Fallback: build checkpoint from current ContextEngine state
            goal = await self._ce.get_goal(job_id)
            if goal is None:
                return None
            job = self._goal_to_job(goal)
            return self._build_checkpoint(job)

        checkpoint_data = await self._persist_store.load(self._checkpoint_key(job_id))
        if checkpoint_data is None or not isinstance(checkpoint_data, dict):
            return None

        try:
            return JobCheckpoint.model_validate(checkpoint_data)
        except Exception:
            logger.warning("Invalid checkpoint data for job %s", job_id, exc_info=True)
            return None

    async def list_jobs(
        self,
        *,
        status: JobState | None = None,
        limit: int = 100,
    ) -> list[Job]:
        """List jobs (root goals) with optional status filter.

        Args:
            status: Optional status filter applied to results.
            limit: Maximum number of jobs to return.

        Returns:
            List of Job entities matching filter criteria.
        """
        status_filter = status.value if status else None
        goals = await self._ce.list_goals(status=status_filter)

        # Filter to root goals only (parent_id == None)
        root_goals = [g for g in goals if g.parent_id is None]

        # Sort by priority descending, then by created_at descending
        root_goals.sort(key=lambda g: (g.priority, g.created_at), reverse=True)

        # Convert to Job entities
        jobs = [self._goal_to_job(g) for g in root_goals]

        # Apply client-side status filter if CE didn't filter
        if status is not None:
            jobs = [j for j in jobs if j.state == status]

        # Apply limit
        return jobs[:limit]

    async def get_job_status_response(self, job_id: str) -> dict[str, Any] | None:
        """Build IPC status response for job (RFC-228 §71-79).

        Args:
            job_id: Job identifier to query.

        Returns:
            Status response dict matching RFC-228 job_status_response schema,
            or None if job not found.
        """
        job = await self.get_job(job_id)
        if job is None:
            return None

        # Count descendant goals for DAG metrics
        all_goals = await self._ce.list_goals()
        descendant_ids = self._collect_descendant_ids(job_id, all_goals)
        descendants = [g for g in all_goals if g.id in descendant_ids]

        total_goals = 1 + len(descendants)
        completed_goals = 1 if job.state in JOB_TERMINAL_STATES else 0
        completed_goals += sum(1 for g in descendants if g.status in ("completed", "validated"))
        failed_goals = 1 if job.state == JobState.FAILED else 0
        failed_goals += sum(1 for g in descendants if g.status == "failed")
        active_goals = 1 if job.state == JobState.ACTIVE else 0
        active_goals += sum(1 for g in descendants if g.status == "active")

        response = {
            "job_id": job.id,
            "status": job.state.value,
            "active_goals": active_goals,
            "completed_goals": completed_goals,
            "failed_goals": failed_goals,
            "total_goals": total_goals,
            "total_tokens_used": job.total_tokens_used,
            "total_duration_ms": job.total_duration_ms,
            "last_error": job.error,
            "worker_id": job.worker_id,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        }

        return response

    # ── Checkpoint Persistence ────────────────────────────────────────────

    async def _persist_checkpoint(self, job_id: str, checkpoint: JobCheckpoint) -> None:
        """Persist job checkpoint to AsyncPersistStore.

        Args:
            job_id: Job identifier.
            checkpoint: JobCheckpoint to persist.
        """
        if self._persist_store is None:
            return

        try:
            await self._persist_store.save(
                self._checkpoint_key(job_id),
                checkpoint.model_dump(mode="json"),
            )
            logger.debug("Persisted checkpoint for job %s", job_id)
        except Exception:
            logger.warning("Failed to persist checkpoint for job %s", job_id, exc_info=True)

    async def restore_checkpoints(self) -> list[str]:
        """Restore job checkpoints from persistence on daemon startup.

        Scans persistence store for job checkpoints and validates that
        corresponding goals still exist in ContextEngine. Returns list
        of valid job IDs that were restored.

        Returns:
            List of job IDs with valid checkpoints restored.
        """
        if self._persist_store is None:
            return []

        keys = await self._persist_store.list_keys()
        prefix_len = len(_KEY_PREFIX)
        job_ids = [k[prefix_len:] for k in keys if k.startswith(_KEY_PREFIX)]

        restored: list[str] = []
        for job_id in job_ids:
            # Validate that goal still exists (skip checkpoint loading for validation)
            goal = await self._ce.get_goal(job_id)
            if goal is None:
                logger.warning(
                    "Checkpoint for job %s exists but goal missing; deleting checkpoint",
                    job_id,
                )
                await self._persist_store.delete(self._checkpoint_key(job_id))
                continue

            # Load checkpoint to validate it's parseable
            checkpoint = await self.get_job_checkpoint(job_id)
            if checkpoint is None:
                logger.warning("Checkpoint for job %s is invalid; deleting", job_id)
                await self._persist_store.delete(self._checkpoint_key(job_id))
                continue

            restored.append(job_id)
            logger.debug("Restored checkpoint for job %s", job_id)

        logger.info("Restored %d job checkpoints from persistence", len(restored))
        return restored

    async def delete_checkpoint(self, job_id: str) -> bool:
        """Delete job checkpoint from persistence.

        Args:
            job_id: Job identifier.

        Returns:
            True if checkpoint was deleted, False if not found.
        """
        if self._persist_store is None:
            return False

        key = self._checkpoint_key(job_id)
        existing = await self._persist_store.load(key)
        if existing is None:
            return False

        await self._persist_store.delete(key)
        logger.debug("Deleted checkpoint for job %s", job_id)
        return True

    # ── Helper Methods ────────────────────────────────────────────────────

    def _goal_to_job(self, goal: GoalNode) -> Job:
        """Convert GoalNode to Job entity.

        Args:
            goal: GoalNode to convert (must be root goal).

        Returns:
            Job entity with fields mapped from GoalNode.
        """
        # Map GoalStatus to JobState
        state_map: dict[str, JobState] = {
            "pending": JobState.PENDING,
            "active": JobState.ACTIVE,
            "completed": JobState.COMPLETED,
            "failed": JobState.FAILED,
            "cancelled": JobState.CANCELLED,
            "suspended": JobState.SUSPENDED,
            "blocked": JobState.BLOCKED,
            "validated": JobState.VALIDATED,
            "awaiting_clarification": JobState.AWAITING_CLARIFICATION,
        }

        job_state = state_map.get(goal.status, JobState.PENDING)

        # Build Job entity from GoalNode fields
        job = Job(
            id=goal.id,
            description=goal.description,
            state=job_state,
            priority=goal.priority,
            created_at=goal.created_at,
            updated_at=goal.updated_at,
            worker_id=goal.assigned_loop_id,
            workspace=goal.workspace,
            source_file=goal.source_file,
            total_tokens_used=goal.total_tokens_used,
            total_duration_ms=goal.total_duration_ms,
            error=goal.error,
            guidance_count=len(goal.guidance_accumulated),
            report=goal.report,
        )

        return job

    def _build_checkpoint(self, job: Job) -> JobCheckpoint:
        """Build JobCheckpoint from Job entity.

        Args:
            job: Job entity to build checkpoint from.

        Returns:
            JobCheckpoint with current job state.
        """
        checkpoint = JobCheckpoint(
            job_id=job.id,
            state=job.state,
            created_at=job.created_at,
            updated_at=job.updated_at,
            worker_id=job.worker_id,
            total_goals=job.total_goals,
            completed_goals=job.completed_goals,
            failed_goals=job.failed_goals,
            active_goals=job.active_goals,
            total_tokens_used=job.total_tokens_used,
            total_duration_ms=job.total_duration_ms,
            last_error=job.error,
            schema_version="1.0",
        )

        return checkpoint

    def _collect_descendant_ids(self, root_id: str, goals: list[GoalNode]) -> set[str]:
        """Collect all descendant goal IDs for a root job.

        Args:
            root_id: Root job ID.
            goals: All goals from ContextEngine.

        Returns:
            Set of descendant goal IDs (excluding root itself).
        """
        # Build parent-to-children map
        children_by_parent: dict[str, list[str]] = {}
        for goal in goals:
            if goal.parent_id:
                children_by_parent.setdefault(goal.parent_id, []).append(goal.id)

        # BFS traversal from root
        descendants: set[str] = set()
        queue = [root_id]
        while queue:
            parent_id = queue.pop(0)
            children = children_by_parent.get(parent_id, [])
            for child_id in children:
                descendants.add(child_id)
                queue.append(child_id)

        return descendants


__all__ = ["JobManager"]
