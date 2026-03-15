"""Lightweight goal lifecycle manager for autonomous iteration (RFC-0007).

The GoalEngine manages goal CRUD, priority scheduling, and retry policy.
It does NOT perform reasoning -- that is the responsibility of the LLM agent
and PlannerProtocol. The runner drives the engine synchronously.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

GoalStatus = Literal["pending", "active", "completed", "failed"]


class Goal(BaseModel):
    """A single autonomous goal.

    Args:
        id: Unique 8-char hex identifier.
        description: Human-readable goal text.
        status: Current lifecycle status.
        priority: Scheduling priority (0-100, higher = first).
        parent_id: Optional parent goal for hierarchical decomposition.
        retry_count: Number of retries attempted so far.
        max_retries: Maximum retries before permanent failure.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str
    status: GoalStatus = "pending"
    priority: int = 50
    parent_id: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GoalEngine:
    """Priority-based goal lifecycle manager.

    Goals are stored in memory and persisted via DurabilityProtocol.
    Scheduling: highest priority first, oldest creation time as tiebreaker.

    Args:
        max_retries: Default max retries for new goals.
    """

    def __init__(self, max_retries: int = 2) -> None:
        self._goals: dict[str, Goal] = {}
        self._max_retries = max_retries

    async def create_goal(
        self,
        description: str,
        *,
        priority: int = 50,
        parent_id: str | None = None,
        max_retries: int | None = None,
    ) -> Goal:
        """Create a new goal.

        Args:
            description: Human-readable goal text.
            priority: Scheduling priority (0-100).
            parent_id: Optional parent goal ID.
            max_retries: Override default max retries.

        Returns:
            The created Goal.
        """
        goal = Goal(
            description=description,
            priority=priority,
            parent_id=parent_id,
            max_retries=max_retries if max_retries is not None else self._max_retries,
        )
        self._goals[goal.id] = goal
        logger.info("Created goal %s: %s (priority=%d)", goal.id, description, priority)
        return goal

    async def next_goal(self) -> Goal | None:
        """Return the highest-priority pending or active goal.

        Scheduling: ``(priority DESC, created_at ASC)``.

        Returns:
            Next goal to process, or None if no executable goals.
        """
        executable = [g for g in self._goals.values() if g.status in ("pending", "active")]
        if not executable:
            return None
        executable.sort(key=lambda g: (-g.priority, g.created_at))
        goal = executable[0]
        if goal.status == "pending":
            goal.status = "active"
            goal.updated_at = datetime.now(timezone.utc)
        return goal

    async def complete_goal(self, goal_id: str) -> Goal:
        """Mark a goal as completed.

        Args:
            goal_id: Goal to complete.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            raise KeyError(f"Goal {goal_id} not found")
        goal.status = "completed"
        goal.updated_at = datetime.now(timezone.utc)
        logger.info("Completed goal %s: %s", goal_id, goal.description)
        return goal

    async def fail_goal(
        self,
        goal_id: str,
        *,
        error: str = "",
        allow_retry: bool = True,
    ) -> Goal:
        """Mark a goal as failed, with optional retry.

        If ``allow_retry`` and retries remain, resets to pending.
        Otherwise marks permanently failed.

        Args:
            goal_id: Goal to fail.
            error: Error description.
            allow_retry: Whether to allow retry if retries remain.

        Returns:
            The updated Goal (may be pending if retrying, failed otherwise).

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            raise KeyError(f"Goal {goal_id} not found")

        if allow_retry and goal.retry_count < goal.max_retries:
            goal.retry_count += 1
            goal.status = "pending"
            goal.updated_at = datetime.now(timezone.utc)
            logger.info(
                "Goal %s retry %d/%d: %s%s",
                goal_id,
                goal.retry_count,
                goal.max_retries,
                goal.description,
                f" - {error}" if error else "",
            )
            return goal

        goal.status = "failed"
        goal.updated_at = datetime.now(timezone.utc)
        logger.warning("Failed goal %s: %s%s", goal_id, goal.description, f" - {error}" if error else "")
        return goal

    async def list_goals(self, status: GoalStatus | None = None) -> list[Goal]:
        """List goals, optionally filtered by status.

        Args:
            status: Filter by status, or None for all.

        Returns:
            List of matching goals.
        """
        if status:
            return [g for g in self._goals.values() if g.status == status]
        return list(self._goals.values())

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Get a goal by ID.

        Args:
            goal_id: Goal ID to look up.

        Returns:
            The Goal, or None if not found.
        """
        return self._goals.get(goal_id)

    def snapshot(self) -> list[dict[str, Any]]:
        """Serialize all goals to a list of dicts for persistence."""
        return [g.model_dump(mode="json") for g in self._goals.values()]

    def restore_from_snapshot(self, data: list[dict[str, Any]]) -> None:
        """Restore goals from a serialized snapshot.

        Args:
            data: List of goal dicts from ``snapshot()``.
        """
        self._goals.clear()
        for item in data:
            try:
                goal = Goal(**item)
                self._goals[goal.id] = goal
            except Exception:
                logger.debug("Skipping invalid goal record: %s", item, exc_info=True)
        logger.info("Restored %d goals", len(self._goals))
