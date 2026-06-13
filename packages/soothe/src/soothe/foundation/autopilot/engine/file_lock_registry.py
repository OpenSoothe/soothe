"""File lock registry for multi-AL conflict tracking (RFC-222).

This module provides file lock tracking for Autopilot mode when
multiple StrangeLoop workers may attempt concurrent file operations.
Prevents conflicts by tracking locks per (goal_id, loop_id).

Architecture:
- FileLockEntry: Per-file lock state (goal, loop, operation)
- FileLockRegistry: GE's view of locks across all active goals
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class FileLockEntry(BaseModel):
    """Entry for a locked file.

    Tracks which goal/loop holds the lock and the operation type.

    Args:
        file_path: Path to the locked file.
        goal_id: Goal that owns the lock.
        loop_id: StrangeLoop that acquired the lock.
        locked_at: Lock acquisition timestamp.
        operation: Type of file operation.
    """

    file_path: str
    goal_id: str
    loop_id: str
    locked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    operation: Literal["edit", "write", "delete"] = "edit"


class FileLockRegistry(BaseModel):
    """GE's view of file locks across all active goals.

    Provides conflict detection for multi-AL file operations.
    Each lock is keyed by file_path with goal_id and loop_id tracking.

    Key Principle: Same loop editing same file → ALLOW.
    Different loop editing locked file → BLOCK.

    Args:
        locks: Active file locks by path.
    """

    locks: dict[str, FileLockEntry] = Field(default_factory=dict)

    def get_lock(self, path: str) -> FileLockEntry | None:
        """Get lock entry for a file.

        Args:
            path: File path to check.

        Returns:
            FileLockEntry if locked, None otherwise.
        """
        return self.locks.get(path)

    def is_locked(self, path: str) -> bool:
        """Check if file is locked by any goal.

        Args:
            path: File path to check.

        Returns:
            True if file is locked.
        """
        return path in self.locks

    def is_locked_by_other(self, path: str, loop_id: str) -> bool:
        """Check if file is locked by a different loop.

        Used by FileLockMiddleware to detect conflicts.

        Args:
            path: File path to check.
            loop_id: Current loop's ID.

        Returns:
            True if locked by a different loop.
        """
        lock = self.locks.get(path)
        if lock is None:
            return False
        return lock.loop_id != loop_id

    def is_locked_by_goal(self, path: str, goal_id: str) -> bool:
        """Check if file is locked by a specific goal.

        Args:
            path: File path to check.
            goal_id: Goal ID to check.

        Returns:
            True if locked by this goal.
        """
        lock = self.locks.get(path)
        if lock is None:
            return False
        return lock.goal_id == goal_id

    def acquire_lock(
        self,
        path: str,
        goal_id: str,
        loop_id: str,
        operation: Literal["edit", "write", "delete"] = "edit",
    ) -> FileLockEntry:
        """Acquire lock on a file.

        Args:
            path: File path to lock.
            goal_id: Goal acquiring the lock.
            loop_id: Loop acquiring the lock.
            operation: Operation type.

        Returns:
            The created FileLockEntry.
        """
        entry = FileLockEntry(
            file_path=path,
            goal_id=goal_id,
            loop_id=loop_id,
            operation=operation,
        )
        self.locks[path] = entry
        return entry

    def release_lock(self, path: str) -> FileLockEntry | None:
        """Release lock on a file.

        Args:
            path: File path to release.

        Returns:
            Released FileLockEntry if existed.
        """
        return self.locks.pop(path, None)

    def release_all_for_goal(self, goal_id: str) -> list[str]:
        """Release all locks for a goal.

        Called when goal completes or fails.

        Args:
            goal_id: Goal whose locks to release.

        Returns:
            List of released file paths.
        """
        released = []
        for path, lock in list(self.locks.items()):
            if lock.goal_id == goal_id:
                self.locks.pop(path)
                released.append(path)
        return released

    def release_all_for_loop(self, loop_id: str) -> list[str]:
        """Release all locks for a loop.

        Called when loop is released or has error.

        Args:
            loop_id: Loop whose locks to release.

        Returns:
            List of released file paths.
        """
        released = []
        for path, lock in list(self.locks.items()):
            if lock.loop_id == loop_id:
                self.locks.pop(path)
                released.append(path)
        return released

    def get_locks_for_goal(self, goal_id: str) -> list[FileLockEntry]:
        """Get all locks for a specific goal.

        Args:
            goal_id: Goal to query.

        Returns:
            List of lock entries for this goal.
        """
        return [lock for lock in self.locks.values() if lock.goal_id == goal_id]

    def get_locks_for_loop(self, loop_id: str) -> list[FileLockEntry]:
        """Get all locks for a specific loop.

        Args:
            loop_id: Loop to query.

        Returns:
            List of lock entries for this loop.
        """
        return [lock for lock in self.locks.values() if lock.loop_id == loop_id]

    def has_conflicts_for_goal(self, goal_id: str, loop_id: str | None = None) -> bool:  # noqa: ARG002
        """STUB: Check if goal has any file lock conflicts.

        Always returns False today — implementing this requires goals to
        declare their target files up-front (no such metadata exists yet).
        Reserved for a future scheduling-time conflict check; not used by
        ``ready_goals`` at present.
        """
        return False

    def get_conflicting_goals(self, goal_id: str) -> list[str]:  # noqa: ARG002
        """STUB: Get goal IDs that have file conflicts with this goal.

        Always returns an empty list today. See ``has_conflicts_for_goal``
        for the underlying dependency.
        """
        return []

    def lock_count(self) -> int:
        """Get total number of active locks.

        Returns:
            Lock count.
        """
        return len(self.locks)

    def clear(self) -> None:
        """Clear all locks.

        Used during shutdown or error recovery.
        """
        self.locks.clear()


class FileConflictError(Exception):
    """Exception raised when file lock conflict detected.

    Attributes:
        file_path: Path to conflicting file.
        goal_id: Goal attempting the operation.
        blocking_goal_id: Goal holding the lock.
        blocking_loop_id: Loop holding the lock.
    """

    def __init__(
        self,
        file_path: str,
        goal_id: str,
        blocking_goal_id: str,
        blocking_loop_id: str,
    ) -> None:
        """Initialize file conflict error.

        Args:
            file_path: Path to conflicting file.
            goal_id: Goal attempting the operation.
            blocking_goal_id: Goal holding the lock.
            blocking_loop_id: Loop holding the lock.
        """
        self.file_path = file_path
        self.goal_id = goal_id
        self.blocking_goal_id = blocking_goal_id
        self.blocking_loop_id = blocking_loop_id
        super().__init__(
            f"File {file_path} locked by goal {blocking_goal_id} in loop {blocking_loop_id}"
        )
