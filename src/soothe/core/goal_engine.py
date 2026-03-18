"""Lightweight goal lifecycle manager for autonomous iteration (RFC-0007).

The GoalEngine manages goal CRUD, priority scheduling, and retry policy.
It does NOT perform reasoning -- that is the responsibility of the LLM agent
and PlannerProtocol. The runner drives the engine synchronously.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from soothe.protocols.planner import GoalReport

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
        depends_on: IDs of goals that must complete before this one (DAG edges).
        retry_count: Number of retries attempted so far.
        max_retries: Maximum retries before permanent failure.
        report: JSON-serialized GoalReport from execution (set on completion).
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str
    status: GoalStatus = "pending"
    priority: int = 50
    parent_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 2
    report: GoalReport | None = None  # RFC-0009: structured report (was str | None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GoalEngine:
    """Priority-based goal lifecycle manager.

    Goals are stored in memory and persisted via DurabilityProtocol.
    Scheduling: highest priority first, oldest creation time as tiebreaker.

    Args:
        max_retries: Default max retries for new goals.
    """

    def __init__(self, max_retries: int = 2) -> None:
        """Initialize the goal engine.

        Args:
            max_retries: Default max retries for new goals.
        """
        self._goals: dict[str, Goal] = {}
        self._max_retries = max_retries

    async def create_goal(
        self,
        description: str,
        *,
        priority: int = 50,
        parent_id: str | None = None,
        max_retries: int | None = None,
        _validate_depth: bool = True,
        _max_depth: int = 5,
    ) -> Goal:
        """Create a new goal with safety validation.

        Args:
            description: Human-readable goal text.
            priority: Scheduling priority (0-100).
            parent_id: Optional parent goal ID.
            max_retries: Override default max retries.
            _validate_depth: Whether to validate goal depth.
            _max_depth: Maximum allowed goal depth.

        Returns:
            The created Goal.

        Raises:
            ValueError: If depth limit exceeded or parent not found.
        """
        # Validate parent exists
        if parent_id:
            parent = self._goals.get(parent_id)
            if not parent:
                msg = f"Parent goal {parent_id} not found"
                raise ValueError(msg)

            # Check depth limit
            if _validate_depth:
                depth = self._calculate_goal_depth(parent_id)
                if depth >= _max_depth:
                    msg = f"Goal depth limit ({_max_depth}) exceeded. Parent {parent_id} is at depth {depth}."
                    raise ValueError(msg)

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
        """Return the highest-priority ready goal (backward-compatible).

        Delegates to ``ready_goals(1)`` for DAG-aware scheduling.

        Returns:
            Next goal to process, or None if no executable goals.
        """
        goals = await self.ready_goals(limit=1)
        return goals[0] if goals else None

    async def ready_goals(self, limit: int = 1) -> list[Goal]:
        """Return goals whose dependencies are all completed (RFC-0009).

        Goals are eligible if they are ``pending`` or ``active`` and all
        goals in their ``depends_on`` list are ``completed``.  Results
        are sorted by ``(priority DESC, created_at ASC)``.

        Args:
            limit: Max goals to return.

        Returns:
            List of ready goals, activated to ``active`` status.
        """
        ready: list[Goal] = []
        for goal in self._goals.values():
            if goal.status not in ("pending", "active"):
                continue
            deps_met = all(
                self._goals.get(dep_id) is not None and self._goals[dep_id].status == "completed"
                for dep_id in goal.depends_on
            )
            if not deps_met:
                continue
            ready.append(goal)

        ready.sort(key=lambda g: (-g.priority, g.created_at))
        result = ready[:limit]

        for goal in result:
            if goal.status == "pending":
                goal.status = "active"
                goal.updated_at = datetime.now(UTC)

        # Log ready goals (RFC-0009 / IG-026)
        if result:
            logger.info("Ready goals: %d (%s)", len(result), [g.id for g in result])
        else:
            logger.debug("No ready goals (waiting for dependencies)")

        return result

    def is_complete(self) -> bool:
        """Check if all goals are terminal (completed or failed).

        Returns:
            True if no pending or active goals remain.
        """
        if not self._goals:
            return True
        return all(g.status in ("completed", "failed") for g in self._goals.values())

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
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        goal.status = "completed"
        goal.updated_at = datetime.now(UTC)
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
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)

        if allow_retry and goal.retry_count < goal.max_retries:
            goal.retry_count += 1
            goal.status = "pending"
            goal.updated_at = datetime.now(UTC)
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
        goal.updated_at = datetime.now(UTC)
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

    def _calculate_goal_depth(self, goal_id: str) -> int:
        """Calculate depth in goal hierarchy.

        Args:
            goal_id: Goal ID to calculate depth for.

        Returns:
            Depth value (0 = no parent, 1 = one parent, etc.).
        """
        max_depth_limit = 20  # Safety limit to prevent infinite loops
        depth = 0
        current_id = goal_id
        visited = set()

        while current_id:
            if current_id in visited:
                break  # Cycle detected
            visited.add(current_id)

            goal = self._goals.get(current_id)
            if not goal:
                break

            depth += 1
            current_id = goal.parent_id

            if depth > max_depth_limit:
                break

        return depth

    def _would_create_cycle(self, goal_id: str, new_deps: list[str]) -> bool:
        """Check if adding new_deps to goal_id would create a cycle using DFS.

        Args:
            goal_id: Target goal ID.
            new_deps: Proposed new dependencies.

        Returns:
            True if adding dependencies would create a cycle.
        """
        visited = set()

        def _dfs(current_id: str) -> bool:
            if current_id == goal_id:
                return True  # Cycle detected
            if current_id in visited:
                return False
            visited.add(current_id)

            current_goal = self._goals.get(current_id)
            if current_goal:
                return any(_dfs(dep_id) for dep_id in current_goal.depends_on)
            return False

        return any(_dfs(dep_id) for dep_id in new_deps)

    async def validate_dependency(self, goal_id: str, depends_on: list[str]) -> tuple[bool, str]:
        """Validate that adding dependencies won't create a cycle.

        Args:
            goal_id: Target goal ID.
            depends_on: Proposed new dependencies.

        Returns:
            Tuple of (is_valid, error_message).
        """
        # Check dependencies exist
        for dep_id in depends_on:
            if dep_id not in self._goals:
                return False, f"Dependency goal {dep_id} does not exist"

        # Check for self-dependency
        if goal_id in depends_on:
            msg = f"Goal {goal_id} cannot depend on itself"
            return False, msg

        # Check for cycles
        if self._would_create_cycle(goal_id, depends_on):
            return False, "Adding dependencies would create a cycle"

        return True, ""

    async def add_dependencies(self, goal_id: str, depends_on: list[str]) -> Goal:
        """Add dependencies to a goal with cycle validation.

        Args:
            goal_id: Target goal ID.
            depends_on: Dependencies to add.

        Returns:
            The updated Goal.

        Raises:
            ValueError: If dependencies would create a cycle.
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)

        is_valid, error = await self.validate_dependency(goal_id, depends_on)
        if not is_valid:
            raise ValueError(error)

        # Add new dependencies (avoid duplicates)
        existing = set(goal.depends_on)
        for dep_id in depends_on:
            if dep_id not in existing:
                goal.depends_on.append(dep_id)

        goal.updated_at = datetime.now(UTC)
        logger.info("Added dependencies to goal %s: %s", goal_id, depends_on)
        return goal

    def snapshot(self) -> list[dict[str, Any]]:
        """Serialize all goals to a list of dicts for persistence."""
        result = []
        for g in self._goals.values():
            goal_dict = g.model_dump(mode="json")
            # Serialize GoalReport to JSON string if present
            if g.report is not None:
                goal_dict["report"] = g.report.model_dump_json()
            result.append(goal_dict)
        return result

    def restore_from_snapshot(self, data: list[dict[str, Any]]) -> None:
        """Restore goals from a serialized snapshot.

        Args:
            data: List of goal dicts from ``snapshot()``.
        """
        self._goals.clear()
        for item in data:
            try:
                # Deserialize GoalReport from JSON string if present
                if "report" in item and isinstance(item["report"], str):
                    item["report"] = GoalReport.model_validate_json(item["report"])
                goal = Goal(**item)
                self._goals[goal.id] = goal
            except Exception:
                logger.debug("Skipping invalid goal record: %s", item, exc_info=True)
        logger.info("Restored %d goals", len(self._goals))
