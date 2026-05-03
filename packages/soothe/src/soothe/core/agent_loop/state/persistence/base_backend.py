"""Abstract backend interface for AgentLoop persistence.

IG-055: Backend-agnostic persistence layer supporting PostgreSQL and SQLite.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class AgentLoopPersistenceBackend(ABC):
    """Abstract backend for AgentLoop persistence operations.

    Defines contract for backend-agnostic operations supporting both PostgreSQL and SQLite.
    All method signatures mirror AgentLoopCheckpointPersistenceManager methods for gradual migration.
    """

    # Core loop operations

    @abstractmethod
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
        pass

    @abstractmethod
    async def get_loop_metadata(self, loop_id: str) -> dict | None:
        """Get loop metadata for daemon reconstruction.

        Args:
            loop_id: Loop identifier.

        Returns:
            Loop metadata dict if found, None otherwise.
        """
        pass

    # Checkpoint anchor operations

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    # Failed branch operations

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def prune_old_branches(self, loop_id: str, max_age_days: int = 30) -> int:
        """Prune old failed branches.

        Args:
            loop_id: AgentLoop identifier.
            max_age_days: Maximum age in days.

        Returns:
            Number of branches pruned.
        """
        pass

    # Goal record operations

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    # Cleanup

    @abstractmethod
    async def close(self) -> None:
        """Close backend connections and cleanup resources."""
        pass
