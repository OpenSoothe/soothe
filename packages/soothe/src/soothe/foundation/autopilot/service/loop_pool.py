"""Loop pool models for AutopilotService (RFC-222).

This module defines data models for managing AgentLoop worker pools:
- LoopHandle: Individual loop state (active, idle, history)
- LoopPool: Pool management (max capacity, goal-to-loop mapping)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LoopHandle(BaseModel):
    """Handle for an AgentLoop worker in the pool.

    Tracks loop state, current goal assignment, and execution history.
    Used for lineage-aware loop reuse and idle timeout management.

    Args:
        loop_id: Unique identifier for this loop.
        current_goal_id: Goal currently executing (None if idle).
        goal_history: List of completed goal IDs (for lineage).
        status: Current loop state.
        idle_since: Timestamp when loop became idle.
        created_at: Loop creation timestamp.
        working_memory: Optional preserved context from previous goal.
    """

    loop_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    current_goal_id: str | None = None
    goal_history: list[str] = Field(default_factory=list)
    status: Literal["active", "idle", "completed", "error"] = "idle"
    idle_since: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Context preservation for lineage reuse
    working_memory: dict[str, Any] = Field(default_factory=dict)

    def assign_goal(self, goal_id: str) -> None:
        """Assign a goal to this loop.

        Updates status to active, clears idle timestamp, adds
        previous goal to history if exists.

        Args:
            goal_id: Goal to assign.
        """
        if self.current_goal_id:
            self.goal_history.append(self.current_goal_id)
        self.current_goal_id = goal_id
        self.status = "active"
        self.idle_since = None

    def release_goal(self, success: bool = True) -> None:
        """Release goal from this loop.

        Updates status to idle or error, sets idle timestamp,
        adds goal to history.

        Args:
            success: Whether goal completed successfully.
        """
        if self.current_goal_id:
            self.goal_history.append(self.current_goal_id)
        self.current_goal_id = None
        self.status = "idle" if success else "error"
        self.idle_since = datetime.now(UTC)

    def mark_idle(self) -> None:
        """Mark loop as idle without goal release.

        Used when goal completes successfully and loop waits
        for new assignment.
        """
        self.status = "idle"
        self.idle_since = datetime.now(UTC)

    def get_history_count(self) -> int:
        """Get number of goals processed by this loop.

        Returns:
            Count of goals in history + current if active.
        """
        count = len(self.goal_history)
        if self.current_goal_id:
            count += 1
        return count

    def can_reuse_for_child(self, parent_goal_id: str) -> bool:
        """Check if loop can be reused for child goal.

        Args:
            parent_goal_id: Parent goal ID to check lineage.

        Returns:
            True if loop's last goal was parent and status allows reuse.
        """
        if self.status not in ("active", "idle"):
            return False

        # If currently executing parent → reuse allowed
        if self.current_goal_id == parent_goal_id:
            return True

        # If idle (no current goal) and last history entry is parent → reuse allowed
        if (
            self.current_goal_id is None
            and self.goal_history
            and self.goal_history[-1] == parent_goal_id
        ):
            return True

        # Otherwise (executing different goal, or parent not last) → no reuse
        return False


class LoopPool(BaseModel):
    """Pool of AgentLoop workers for AutopilotService.

    Manages loop creation, assignment, and release. Tracks
    goal-to-loop mapping for lineage reuse.

    Args:
        loops: Active and idle loops by loop_id.
        goal_to_loop: Mapping of completed goals to their loop.
        idle_loops: Queue of idle loop_ids waiting for assignment.
        max_loops: Maximum concurrent loops.
        active_tasks: Running asyncio.Task references by loop_id.
    """

    loops: dict[str, LoopHandle] = Field(default_factory=dict)
    goal_to_loop: dict[str, str] = Field(default_factory=dict)  # goal_id → loop_id
    idle_loops: list[str] = Field(default_factory=list)  # queue of idle loop_ids
    max_loops: int = 4
    active_tasks: dict[str, Any] = Field(default_factory=dict)  # loop_id → asyncio.Task

    def active_count(self) -> int:
        """Count active loops.

        Returns:
            Number of loops with status "active".
        """
        return sum(1 for loop in self.loops.values() if loop.status == "active")

    def idle_count(self) -> int:
        """Count idle loops.

        Returns:
            Number of loops with status "idle".
        """
        return sum(1 for loop in self.loops.values() if loop.status == "idle")

    def total_count(self) -> int:
        """Count all loops.

        Returns:
            Total number of loops in pool.
        """
        return len(self.loops)

    def can_spawn(self) -> bool:
        """Check if new loop can be spawned.

        Returns:
            True if under max_loops limit.
        """
        return len(self.loops) < self.max_loops

    def get_loop_for_goal(self, goal_id: str) -> LoopHandle | None:
        """Get loop assigned to a goal.

        Args:
            goal_id: Goal to look up.

        Returns:
            LoopHandle if found, None otherwise.
        """
        loop_id = self.goal_to_loop.get(goal_id)
        if loop_id:
            return self.loops.get(loop_id)
        return None

    def add_loop(self, loop: LoopHandle) -> None:
        """Add loop to pool.

        Args:
            loop: LoopHandle to add.
        """
        self.loops[loop.loop_id] = loop
        if loop.status == "idle":
            self.idle_loops.append(loop.loop_id)

    def remove_loop(self, loop_id: str) -> LoopHandle | None:
        """Remove loop from pool.

        Args:
            loop_id: Loop to remove.

        Returns:
            Removed LoopHandle if found.
        """
        loop = self.loops.pop(loop_id, None)
        if loop:
            # Remove from idle queue if present
            self.idle_loops = [id_ for id_ in self.idle_loops if id_ != loop_id]
            # Remove from active tasks if present
            self.active_tasks.pop(loop_id, None)
            # Clean up goal mappings for this loop
            for goal_id, mapped_loop_id in list(self.goal_to_loop.items()):
                if mapped_loop_id == loop_id:
                    self.goal_to_loop.pop(goal_id)
        return loop

    def pop_idle_loop(self) -> LoopHandle | None:
        """Get and remove first idle loop from queue.

        Returns:
            LoopHandle if idle loops available.
        """
        if self.idle_loops:
            loop_id = self.idle_loops.pop(0)
            return self.loops.get(loop_id)
        return None

    def assign_loop_to_goal(self, loop: LoopHandle, goal_id: str) -> None:
        """Assign loop to goal and update mappings.

        Args:
            loop: LoopHandle to assign.
            goal_id: Goal to assign to.
        """
        loop.assign_goal(goal_id)
        self.goal_to_loop[goal_id] = loop.loop_id
        # Remove from idle queue if was idle
        self.idle_loops = [id_ for id_ in self.idle_loops if id_ != loop.loop_id]

    def record_goal_completion(self, goal_id: str, loop_id: str) -> None:
        """Record goal completion in loop history.

        Args:
            goal_id: Completed goal.
            loop_id: Loop that processed it.
        """
        loop = self.loops.get(loop_id)
        if loop:
            loop.release_goal(success=True)
            self.idle_loops.append(loop_id)
            # Keep goal-to-loop mapping for lineage
            self.goal_to_loop[goal_id] = loop_id

    def record_goal_failure(self, goal_id: str, loop_id: str) -> None:
        """Record goal failure.

        Args:
            goal_id: Failed goal.
            loop_id: Loop that failed.
        """
        loop = self.loops.get(loop_id)
        if loop:
            loop.release_goal(success=False)
            # Remove from active tasks
            self.active_tasks.pop(loop_id, None)
            # Keep goal-to-loop mapping for debugging
            self.goal_to_loop[goal_id] = loop_id

    def has_capacity(self) -> bool:
        """Check if pool has capacity for new goal.

        Returns:
            True if idle loops available or can spawn.
        """
        return bool(self.idle_loops) or self.can_spawn()
