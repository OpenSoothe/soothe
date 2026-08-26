"""Abstract backend interface for StrangeLoop persistence.

Backend-agnostic persistence layer supporting PostgreSQL and SQLite.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class StrangeLoopPersistenceBackend(ABC):
    """Abstract backend for StrangeLoop persistence operations.

    Defines contract for backend-agnostic operations supporting both PostgreSQL and SQLite.
    Mirrors ``StrangeLoopCheckpointPersistenceManager`` persistence operations.
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
        """Register new StrangeLoop in database.

        Args:
            loop_id: StrangeLoop identifier.
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

    @abstractmethod
    async def update_loop_metadata(
        self, loop_id: str, *, force_status: bool = False, **fields: Any
    ) -> None:
        """Partially update loop metadata fields.

        Args:
            loop_id: Loop identifier.
            force_status: When True, bypass the RFC-225 goal-count guard so
                an authoritative caller (stale-loop reconciler) can demote a
                confirmed-dead zombie loop's ``status`` even when it has goals.
            **fields: Column names and values to update. Supported keys:
                status, current_thread_id, thread_ids, client_workspace,
                detached_at, total_goals_completed, total_thread_switches,
                total_duration_ms, total_tokens_used, updated_at.
        """
        pass

    @abstractmethod
    async def mark_running_goals_failed(self, loop_id: str) -> int:
        """Mark a loop's still-``running`` goal_records as ``failed``.

        Returns the count of goal rows updated. Used by the stale-loop
        reconciler to close goals orphaned by a crashed runner.
        """
        pass

    @abstractmethod
    async def list_loops(
        self,
        status_filter: str | None = None,
        limit: int = 100,
        workspace_filter: str | None = None,
    ) -> list[dict]:
        """Return summary rows for all loops, ordered by created_at DESC.

        Args:
            status_filter: Optional status value to filter by.
            limit: Maximum rows to return.
            workspace_filter: Optional client_workspace path to filter by.

        Returns:
            List of dicts with keys: loop_id, status, thread_ids, current_thread_id,
            total_goals_completed, total_thread_switches, created_at, updated_at,
            client_workspace, detached_at.
        """
        pass

    # Goal record operations

    @abstractmethod
    async def save_goal_record(
        self,
        goal_id: str,
        loop_id: str,
        thread_id: str,
        status: str,
        started_at: str,
    ) -> None:
        """Save goal index entry.

        Args:
            goal_id: Goal identifier.
            loop_id: StrangeLoop identifier.
            thread_id: Thread identifier.
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
        duration_ms: int,
        tokens_used: int,
        completed_at: str | None,
    ) -> None:
        """Update goal index entry.

        Args:
            goal_id: Goal identifier.
            loop_id: StrangeLoop identifier.
            status: Goal status.
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
