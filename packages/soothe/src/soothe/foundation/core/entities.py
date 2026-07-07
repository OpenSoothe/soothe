"""Core entities module (RFC-228, RFC-626).

This module provides core entity abstractions for job management:
- Job: Facade over root GoalNode
- JobState: Job lifecycle state enum
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.foundation.context.models import GoalNode


class JobState(StrEnum):
    """Job lifecycle state aligned with GoalStatus (RFC-228, RFC-626).

    Job states map directly to GoalNode.status for root goals. These states
    are used in IPC responses and desktop app job listing.

    Attributes:
        PENDING: Job created but not yet scheduled for execution.
        ACTIVE: Job currently executing with assigned worker.
        SUSPENDED: Job paused by user or system, awaiting resume.
        BLOCKED: Job blocked on dependency or awaiting clarification.
        COMPLETED: Job successfully completed (terminal state).
        FAILED: Job failed after exhausting retries (terminal state).
        CANCELLED: Job cancelled by user or system (terminal state).
        VALIDATED: Job completed and validated by verification rules.
        AWAITING_CLARIFICATION: Job blocked waiting for user input (RFC-622).
    """

    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    VALIDATED = "validated"
    AWAITING_CLARIFICATION = "awaiting_clarification"


@dataclass(frozen=True)
class Job:
    """Job entity representing a root GoalNode (RFC-228, RFC-626 §2).

    A Job is a facade over GoalNode with parent_id=None. It provides
    job-specific operations and queries that operate directly on
    ContextEngine without intermediate wrapper models.

    Per RFC-626 §2: Job operates directly on GoalNode. No Goal wrapper model,
    no GoalEngine flat dict. Job queries use ContextEngine APIs directly.

    This is an immutable value object that captures a snapshot of job state.
    For mutable operations, use ContextEngine goal APIs.

    Attributes:
        id: Unique job identifier (8-char hex).
        description: Job goal description text.
        state: Current job lifecycle state.
        priority: Job priority (0-100, higher = more urgent).
        created_at: Job creation timestamp.
        updated_at: Last state update timestamp.
        worker_id: Assigned worker loop_id if executing.
        workspace: Workspace path for job execution.
        source_file: Source GOAL.md file path if file-sourced.
        total_goals: Total goals in job DAG subtree.
        completed_goals: Number of completed goals.
        failed_goals: Number of failed goals.
        total_tokens_used: Cumulative token usage.
        total_duration_ms: Cumulative execution duration.
        error: Error message if job failed.
        guidance_count: Number of guidance comments accumulated.
        report: Completion report if job is terminal.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str = ""
    state: JobState = JobState.PENDING
    priority: int = 50
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    worker_id: str | None = None
    workspace: str | None = None
    source_file: str | None = None
    total_goals: int = 1
    completed_goals: int = 0
    failed_goals: int = 0
    active_goals: int = 0
    total_tokens_used: int = 0
    total_duration_ms: int = 0
    error: str | None = None
    guidance_count: int = 0
    report: dict[str, Any] | None = None

    @classmethod
    def from_goal_node(cls, goal: GoalNode, stats: dict[str, Any] | None = None) -> Job:
        """Create Job facade from a root GoalNode.

        Args:
            goal: GoalNode instance with parent_id=None (root goal).
            stats: Optional statistics dict with total_goals, completed_goals, etc.

        Returns:
            Job instance representing the root goal.

        Raises:
            ValueError: If goal is not a root goal (parent_id is not None).
        """
        if goal.parent_id is not None:
            msg = f"Goal {goal.id} is not a root goal (parent_id={goal.parent_id})"
            raise ValueError(msg)

        stats = stats or {}
        return cls(
            id=goal.id,
            description=goal.description,
            state=JobState(goal.status),
            priority=goal.priority,
            created_at=goal.created_at,
            updated_at=goal.updated_at,
            worker_id=goal.assigned_loop_id,
            workspace=goal.workspace,
            source_file=goal.source_file,
            total_goals=stats.get("total_goals", 1),
            completed_goals=stats.get("completed_goals", 0),
            failed_goals=stats.get("failed_goals", 0),
            active_goals=stats.get("active_goals", 0),
            total_tokens_used=goal.total_tokens_used,
            total_duration_ms=goal.total_duration_ms,
            error=goal.error,
            guidance_count=len(goal.guidance_accumulated),
            report=goal.report,
        )

    def is_terminal(self) -> bool:
        """Check if job is in a terminal state.

        Returns:
            True if job state is terminal.
        """
        return self.state in {
            JobState.COMPLETED,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.VALIDATED,
        }

    def is_blocked(self) -> bool:
        """Check if job is blocked from execution.

        Returns:
            True if job state is blocked.
        """
        return self.state in {
            JobState.SUSPENDED,
            JobState.BLOCKED,
            JobState.AWAITING_CLARIFICATION,
        }

    def completion_percentage(self) -> float:
        """Calculate job completion percentage.

        Returns:
            Completion percentage (0.0 to 100.0).
        """
        if self.total_goals == 0:
            return 0.0
        completed_or_failed = self.completed_goals + self.failed_goals
        return (completed_or_failed / self.total_goals) * 100.0

    def __repr__(self) -> str:
        """Return concise representation for debugging."""
        return (
            f"Job(id={self.id}, state={self.state}, "
            f"completion={self.completion_percentage():.1f}%, "
            f"worker={self.worker_id or 'none'})"
        )


__all__ = [
    "Job",
    "JobState",
]
