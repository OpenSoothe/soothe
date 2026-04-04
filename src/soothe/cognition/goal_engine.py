"""Lightweight goal lifecycle manager for autonomous iteration (RFC-0007).

The GoalEngine manages goal CRUD, priority scheduling, and retry policy.
It does NOT perform reasoning -- that is the responsibility of the LLM agent
and PlannerProtocol. The runner drives the engine synchronously.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from soothe.protocols.planner import GoalReport

logger = logging.getLogger(__name__)

# RFC-204: Extended lifecycle states (7 total)
GoalStatus = Literal["pending", "active", "validated", "completed", "failed", "suspended", "blocked"]

# Terminal states that count as "resolved"
TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed"})

# Number of parts expected from frontmatter split (before, yaml, after)
_FRONTMATTER_SPLIT_MIN = 3


class Goal(BaseModel):
    """A single autonomous goal.

    Args:
        id: Unique 8-char hex identifier.
        description: Human-readable goal text.
        status: Current lifecycle status (7 states per RFC-204).
        priority: Scheduling priority (0-100, higher = first).
        parent_id: Optional parent goal for hierarchical decomposition.
        depends_on: IDs of goals that must complete before this one (hard DAG edges).
        informs: IDs of goals whose findings may enrich this goal (soft dependency).
        conflicts_with: IDs of goals that must not execute concurrently (mutual exclusion).
        plan_count: Number of plans created for this goal (for P_N ID generation).
        retry_count: Number of retries attempted so far.
        max_retries: Maximum retries before permanent failure.
        send_back_count: Number of consensus send-backs used (RFC-204).
        max_send_backs: Maximum send-back rounds before suspension (RFC-204).
        report: GoalReport from execution (set on completion).
        source_file: Path to GOAL.md file that defined this goal (None if auto-created).
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str
    status: GoalStatus = "pending"
    priority: int = 50
    parent_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    # RFC-204: Soft relationships and mutual exclusion
    informs: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    plan_count: int = 0
    retry_count: int = 0
    max_retries: int = 2
    # RFC-204: Consensus loop tracking
    send_back_count: int = 0
    max_send_backs: int = 3
    report: GoalReport | None = None
    # RFC-204: Source file for status tracking
    source_file: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GoalEngine:
    """Priority-based goal lifecycle manager.

    Goals are stored in memory and persisted via DurabilityProtocol.
    Scheduling: highest priority first, oldest creation time as tiebreaker.

    Args:
        max_retries: Default max retries for new goals.
    """

    def __init__(self, max_retries: int = 2, max_send_backs: int = 3) -> None:
        """Initialize the goal engine.

        Args:
            max_retries: Default max retries for new goals.
            max_send_backs: Default max consensus send-back rounds (RFC-204).
        """
        self._goals: dict[str, Goal] = {}
        self._max_retries = max_retries
        self._max_send_backs = max_send_backs

    async def create_goal(
        self,
        description: str,
        *,
        priority: int = 50,
        parent_id: str | None = None,
        max_retries: int | None = None,
        max_send_backs: int | None = None,
        informs: list[str] | None = None,
        conflicts_with: list[str] | None = None,
        source_file: str | None = None,
        goal_id: str | None = None,
        depends_on: list[str] | None = None,
        _validate_depth: bool = True,
        _max_depth: int = 5,
    ) -> Goal:
        """Create a new goal with safety validation.

        Args:
            description: Human-readable goal text.
            priority: Scheduling priority (0-100).
            parent_id: Optional parent goal ID.
            max_retries: Override default max retries.
            max_send_backs: Override default max send-back rounds (RFC-204).
            informs: Soft dependency goal IDs (RFC-204).
            conflicts_with: Mutual exclusion goal IDs (RFC-204).
            source_file: Path to GOAL.md that defined this goal (RFC-204).
            goal_id: Override default ID generation (for file-discovered goals).
            depends_on: Hard dependency goal IDs (alternative to post-creation add).
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
            max_send_backs=max_send_backs if max_send_backs is not None else self._max_send_backs,
            informs=informs or [],
            conflicts_with=conflicts_with or [],
            source_file=source_file,
            depends_on=depends_on or [],
        )
        if goal_id:
            goal.id = goal_id
        self._goals[goal.id] = goal

        # Enhanced logging with parent context
        parent_context = ""
        if parent_id:
            parent = self._goals.get(parent_id)
            if parent:
                parent_context = f' | parent: "{parent.description}"'
        logger.info('Created goal %s: "%s"%s (priority=%d)', goal.id, description, parent_context, priority)
        logger.debug(self._format_goal_dag())
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
        """Return goals whose dependencies are all completed (RFC-0009, RFC-204).

        Goals are eligible if they are ``pending`` and all goals in their
        ``depends_on`` list are in terminal states (completed or failed).
        Results are sorted by ``(priority DESC, created_at ASC)``.

        Conflict-aware: goals with ``conflicts_with`` pointing to an ``active``
        goal are deferred to prevent concurrent execution.

        Args:
            limit: Max goals to return.

        Returns:
            List of ready goals, activated to ``active`` status.
        """
        ready: list[Goal] = []
        active_ids = {g.id for g in self._goals.values() if g.status == "active"}

        for goal in self._goals.values():
            if goal.status not in ("pending", "active"):
                continue

            # Hard dependencies: all must be terminal
            deps_met = all(
                (dep := self._goals.get(dep_id)) is not None and dep.status in TERMINAL_STATES
                for dep_id in goal.depends_on
            )
            if not deps_met:
                continue

            # RFC-204: Conflict check — defer if conflicting goal is active
            has_conflict = any(dep_id in active_ids for dep_id in goal.conflicts_with)
            if has_conflict:
                logger.debug("Goal %s deferred: conflict with active goal", goal.id)
                continue

            ready.append(goal)

        ready.sort(key=lambda g: (-g.priority, g.created_at))
        result = ready[:limit]

        for goal in result:
            goal.status = "active"
            goal.updated_at = datetime.now(UTC)

        # Log ready goals (RFC-0009 / IG-026) - Enhanced natural language format
        if result:
            goal_summaries = []
            for g in result:
                context = self._get_goal_context(g.id)
                goal_summaries.append(f'\n  → {g.id}: "{context}" (priority={g.priority})')
            logger.info("Ready goals: %d%s", len(result), "".join(goal_summaries))
        else:
            logger.debug("No ready goals (waiting for dependencies)")

        return result

    def is_complete(self) -> bool:
        """Check if all goals are resolved (completed or failed).

        Returns:
            True if no pending, active, suspended, blocked, or validated goals remain.
        """
        if not self._goals:
            return True
        return all(g.status in TERMINAL_STATES for g in self._goals.values())

    async def validate_goal(self, goal_id: str) -> Goal:
        """RFC-204: Mark goal as validated (Layer 3 accepted completion).

        Args:
            goal_id: Goal to validate.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        goal.status = "validated"
        goal.updated_at = datetime.now(UTC)
        logger.info("Validated goal %s", goal_id)
        return goal

    async def suspend_goal(self, goal_id: str, *, reason: str = "") -> Goal:
        """RFC-204: Suspend a goal due to send-back budget exhaustion.

        Args:
            goal_id: Goal to suspend.
            reason: Why the goal was suspended.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        goal.status = "suspended"
        goal.updated_at = datetime.now(UTC)
        logger.warning("Suspended goal %s: %s", goal_id, reason)
        return goal

    async def block_goal(self, goal_id: str, *, reason: str = "") -> Goal:
        """RFC-204: Block a goal awaiting external input.

        Args:
            goal_id: Goal to block.
            reason: Why the goal was blocked.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        goal.status = "blocked"
        goal.updated_at = datetime.now(UTC)
        logger.warning("Blocked goal %s: %s", goal_id, reason)
        return goal

    async def reactivate_goal(self, goal_id: str) -> Goal:
        """RFC-204: Reactivate a suspended/blocked goal back to pending.

        Args:
            goal_id: Goal to reactivate.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        if goal.status not in ("suspended", "blocked"):
            msg = f"Goal {goal_id} is {goal.status}, not suspended/blocked"
            raise ValueError(msg)
        goal.status = "pending"
        goal.send_back_count = 0  # Reset send-back budget
        goal.updated_at = datetime.now(UTC)
        logger.info("Reactivated goal %s (was %s)", goal_id, goal.status)
        return goal

    async def check_reactivated_goals(self) -> list[Goal]:
        """RFC-204: Auto-reactivate goals whose dependencies are now resolved.

        After a goal completes, check if suspended or blocked goals now have
        their dependencies satisfied.

        Returns:
            List of reactivated goals.
        """
        reactivated = []
        for goal in self._goals.values():
            if goal.status not in ("suspended", "blocked"):
                continue
            deps_met = all(
                (dep := self._goals.get(dep_id)) is not None and dep.status in TERMINAL_STATES
                for dep_id in goal.depends_on
            )
            if deps_met:
                goal.status = "pending"
                goal.send_back_count = 0
                goal.updated_at = datetime.now(UTC)
                reactivated.append(goal)
                logger.info("Auto-reactivated goal %s (dependencies resolved)", goal.id)
        return reactivated

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

        # Calculate duration before updating timestamp
        duration = (datetime.now(UTC) - goal.created_at).total_seconds()

        goal.status = "completed"
        goal.updated_at = datetime.now(UTC)

        # Enhanced logging with parent context and duration
        parent_context = ""
        if goal.parent_id:
            parent = self._goals.get(goal.parent_id)
            if parent:
                parent_context = f' | parent: "{parent.description}"'
        logger.info(
            'Completed goal %s: "%s"%s (priority=%d, duration=%.1fs)',
            goal_id,
            goal.description,
            parent_context,
            goal.priority,
            duration,
        )
        logger.debug(self._format_goal_dag())
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
            logger.debug(self._format_goal_dag())
            return goal

        goal.status = "failed"
        goal.updated_at = datetime.now(UTC)

        # Enhanced logging with dependency context and status
        dep_context = ""
        if goal.depends_on:
            dep_descs = []
            for dep_id in goal.depends_on:
                dep = self._goals.get(dep_id)
                if dep:
                    dep_descs.append(f"{dep.description} ({dep.status})")
                else:
                    dep_descs.append(dep_id)
            dep_context = f" | depends_on: [{', '.join(dep_descs)}]"
        logger.warning(
            'Failed goal %s: "%s"%s (priority=%d, retries=%d/%d)%s',
            goal_id,
            goal.description,
            dep_context,
            goal.priority,
            goal.retry_count,
            goal.max_retries,
            f" - {error}" if error else "",
        )
        logger.debug(self._format_goal_dag())
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

        # Enhanced logging with dependency descriptions
        dep_descs = []
        for dep_id in depends_on:
            dep = self._goals.get(dep_id)
            if dep:
                dep_descs.append(f'{dep_id}: "{dep.description}"')
            else:
                dep_descs.append(dep_id)
        logger.info(
            'Added dependencies to goal %s "%s": [%s]',
            goal_id,
            goal.description,
            ", ".join(dep_descs),
        )
        logger.debug(self._format_goal_dag())
        return goal

    def _get_goal_context(self, goal_id: str) -> str:
        """Get natural language context for a goal.

        Args:
            goal_id: Goal ID to get context for.

        Returns:
            Context string with parent and dependency descriptions.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            return goal_id

        context_parts = [goal.description]

        # Add parent context
        if goal.parent_id:
            parent = self._goals.get(goal.parent_id)
            if parent:
                context_parts.append(f"parent: {parent.description}")

        # Add dependency context
        if goal.depends_on:
            dep_descs = []
            for dep_id in goal.depends_on:
                dep = self._goals.get(dep_id)
                if dep:
                    dep_descs.append(dep.description)
                else:
                    dep_descs.append(dep_id)
            context_parts.append(f"depends_on: [{', '.join(dep_descs)}]")

        return " | ".join(context_parts)

    def _format_goal_dag(self) -> str:
        """Format the current goal DAG state for logging.

        Returns:
            Human-readable string representation of the goal DAG.
        """
        if not self._goals:
            return "Goal DAG: (empty)"

        lines = ["Goal DAG:"]
        for goal in sorted(self._goals.values(), key=lambda g: (-g.priority, g.created_at)):
            # Add parent description
            parent_str = ""
            if goal.parent_id:
                parent = self._goals.get(goal.parent_id)
                if parent:
                    parent_str = f' parent={goal.parent_id} "{parent.description[:30]}"'
                else:
                    parent_str = f" parent={goal.parent_id}"

            # Add dependency descriptions
            deps_with_desc = []
            for dep_id in goal.depends_on:
                dep = self._goals.get(dep_id)
                if dep:
                    deps_with_desc.append(f'{dep_id} "{dep.description[:30]}"')
                else:
                    deps_with_desc.append(dep_id)
            deps_str = f" depends_on=[{', '.join(deps_with_desc)}]" if goal.depends_on else ""

            lines.append(
                f"  [{goal.id}] {goal.status} priority={goal.priority}{parent_str}{deps_str}"
                f"\n      → {goal.description}"
            )
        return "\n".join(lines)

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
        logger.debug(self._format_goal_dag())

    # ------------------------------------------------------------------
    # RFC-204: Goal File Discovery & Status Tracking
    # ------------------------------------------------------------------

    async def discover_goals_from_files(
        self,
        autopilot_dir: str | None = None,
    ) -> list[Goal]:
        """RFC-204: Discover goals from GOAL.md/GOALS.md files.

        Scans in priority order:
        1. `SOOTHE_HOME/autopilot/GOAL.md` — single goal mode
        2. `SOOTHE_HOME/autopilot/GOALS.md` — batch mode
        3. `SOOTHE_HOME/autopilot/goals/*/GOAL.md` — per-goal dirs

        Args:
            autopilot_dir: Override path. Defaults to $SOOTHE_HOME/autopilot.

        Returns:
            List of goals created from discovered files.
        """
        from soothe.config import SOOTHE_HOME

        base = Path(autopilot_dir or SOOTHE_HOME) / "autopilot"
        goals_dir = base / "goals"
        goals_created: list[Goal] = []

        # Priority 1: Root GOAL.md (single goal mode)
        single_goal_file = base / "GOAL.md"
        if single_goal_file.exists():
            goal_def = _parse_goal_file(single_goal_file)
            if goal_def:
                goal = await self._create_from_definition(goal_def, source_file=str(single_goal_file))
                goals_created.append(goal)
                return goals_created  # Single goal mode, skip other discovery

        # Priority 2: Root GOALS.md (batch mode)
        goals_batch_file = base / "GOALS.md"
        if goals_batch_file.exists():
            batch_defs = _parse_goals_batch_file(goals_batch_file)
            for gdef in batch_defs:
                goal = await self._create_from_definition(gdef, source_file=str(goals_batch_file))
                goals_created.append(goal)

        # Priority 3: goals/ subdirectory GOAL.md files
        if goals_dir.exists():
            for subdir in sorted(goals_dir.iterdir()):
                if subdir.is_dir():
                    gfile = subdir / "GOAL.md"
                    if gfile.exists():
                        goal_def = _parse_goal_file(gfile)
                        if goal_def:
                            goal = await self._create_from_definition(goal_def, source_file=str(gfile))
                            goals_created.append(goal)

        if goals_created:
            logger.info("Discovered %d goals from files", len(goals_created))
        return goals_created

    async def update_goal_file_status(self, goal_id: str) -> None:
        """RFC-204: Update status in the source GOAL.md file.

        Updates the frontmatter status field to match the goal's current status.

        Args:
            goal_id: Goal whose file status should be updated.
        """
        goal = self._goals.get(goal_id)
        if not goal or not goal.source_file:
            return

        try:
            _update_frontmatter_status(goal.source_file, goal.status)
        except Exception:
            logger.debug("Failed to update goal file status for %s", goal_id, exc_info=True)

    async def append_goal_progress(self, goal_id: str, entry: str) -> None:
        """RFC-204: Append a progress entry to the goal's GOAL.md file.

        Finds or creates a ``## Progress`` section and appends a timestamped entry.

        Args:
            goal_id: Goal ID to update.
            entry: Progress entry text.
        """
        goal = self._goals.get(goal_id)
        if not goal or not goal.source_file:
            return

        source = Path(goal.source_file)
        if not source.exists():  # noqa: ASYNC240
            return

        try:
            from datetime import UTC, datetime

            content = source.read_text()  # noqa: ASYNC240
            timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
            progress_line = f"\n- [{timestamp}] {entry}"

            # Find or create ## Progress section
            if "## Progress" in content:
                # Append after the last ## section header within progress, or at end of file
                parts = content.split("## Progress", 1)
                section = parts[1]
                # Find next ## header after Progress
                next_header_idx = section.find("\n## ")
                if next_header_idx >= 0:
                    # Insert before the next section header
                    before = section[:next_header_idx]
                    after = section[next_header_idx:]
                    content = parts[0] + "## Progress" + before + progress_line + after
                else:
                    content += progress_line
            else:
                # Create Progress section at the end
                content += f"\n## Progress{progress_line}\n"

            source.write_text(content)  # noqa: ASYNC240
        except OSError:
            logger.debug("Failed to append progress for %s", goal_id, exc_info=True)

    # ------------------------------------------------------------------
    # Internal helpers for file discovery
    # ------------------------------------------------------------------

    async def _create_from_definition(
        self,
        goal_def: _GoalFileDefinition,
        *,
        source_file: str,
    ) -> Goal:
        """Create a goal from a parsed file definition."""
        return await self.create_goal(
            description=goal_def.description,
            priority=goal_def.priority,
            goal_id=goal_def.id,
            depends_on=goal_def.depends_on,
            informs=goal_def.informs,
            conflicts_with=goal_def.conflicts_with,
            source_file=source_file,
        )


# ======================================================================
# RFC-204: Goal File Parsing Helpers
# ======================================================================


@dataclass
class _GoalFileDefinition:
    """Parsed definition of a goal from a markdown file."""

    id: str
    description: str
    priority: int = 50
    depends_on: list[str] = field(default_factory=list)
    informs: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)


def _parse_goal_file(path: Path) -> _GoalFileDefinition | None:
    """Parse a single GOAL.md file.

    Expected format:
    ```
    ---
    id: my-goal
    priority: 80
    depends_on: [dep1, dep2]
    informs: [goal3]
    conflicts_with: [goal4]
    ---

    # Title → used as description

    ## Success Criteria
    - criterion 1
    - criterion 2
    ```
    """
    text = path.read_text()
    frontmatter, body = _split_frontmatter(text)
    if not frontmatter:
        return None

    import yaml

    fm = yaml.safe_load(frontmatter) or {}

    # Extract description from first heading
    description = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            description = stripped[2:].strip()
            break
    if not description:
        description = "Goal from " + path.name

    # Extract success criteria
    success_criteria = _extract_success_criteria(body)

    return _GoalFileDefinition(
        id=fm.get("id", path.stem),
        description=description,
        priority=int(fm.get("priority", 50)),
        depends_on=fm.get("depends_on", []),
        informs=fm.get("informs", []),
        conflicts_with=fm.get("conflicts_with", []),
        success_criteria=success_criteria,
    )


def _parse_goals_batch_file(path: Path) -> list[_GoalFileDefinition]:
    """Parse a GOALS.md file with multiple goals.

    Expected format:
    ```
    ## Goal: Authentication System
    - id: auth
    - priority: 90
    - depends_on: []

    Description text becomes the goal description.

    ## Goal:API Integration
    - id: api
    - priority: 70
    - depends_on: [auth]
    ```
    """
    text = path.read_text()
    goals = []

    # Split on ## Goal: headings
    sections = re.split(r"## Goal:\s*", text)[1:]  # skip preamble

    for section in sections:
        lines = section.splitlines()
        # First line is the goal name
        name = lines[0].strip() if lines else ""

        # Parse key-value bullets
        metadata: dict[str, Any] = {}
        body_lines: list[str] = []
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("- id:"):
                metadata["id"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("- priority:"):
                metadata["priority"] = int(stripped.split(":", 1)[1].strip())
            elif stripped.startswith("- depends_on:"):
                raw = stripped.split(":", 1)[1].strip()
                metadata["depends_on"] = _parse_yaml_list(raw)
            elif stripped.startswith("- informs:"):
                raw = stripped.split(":", 1)[1].strip()
                metadata["informs"] = _parse_yaml_list(raw)
            elif stripped.startswith("- conflicts_with:"):
                raw = stripped.split(":", 1)[1].strip()
                metadata["conflicts_with"] = _parse_yaml_list(raw)
            else:
                body_lines.append(line)

        description = name
        if body_lines:
            desc_text = "\n".join(body_lines).strip()
            if desc_text:
                description = f"{name}: {desc_text}"

        goals.append(
            _GoalFileDefinition(
                id=metadata.get("id", name.lower().replace(" ", "-")),
                description=description,
                priority=metadata.get("priority", 50),
                depends_on=metadata.get("depends_on", []),
                informs=metadata.get("informs", []),
                conflicts_with=metadata.get("conflicts_with", []),
            )
        )

    return goals


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split YAML frontmatter from body text."""
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) >= _FRONTMATTER_SPLIT_MIN:
        return parts[1].strip(), parts[2].strip()
    return None, text


def _extract_success_criteria(body: str) -> list[str]:
    """Extract checklist items from Success Criteria section."""
    criteria = []
    in_criteria = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Success Criteria"):
            in_criteria = True
            continue
        if in_criteria:
            if stripped.startswith("- "):
                criteria.append(stripped[2:].strip())
            elif stripped.startswith("##"):
                break
    return criteria


def _parse_yaml_list(raw: str) -> list[str]:
    """Parse a YAML list string like '[a, b]' or '[]'."""
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
    return []


def _update_frontmatter_status(file_path: str, status: str) -> None:
    """Update the status field in YAML frontmatter of a markdown file."""
    path = Path(file_path)
    text = path.read_text()
    frontmatter, body = _split_frontmatter(text)
    if not frontmatter:
        return

    import yaml

    fm = yaml.safe_load(frontmatter) or {}
    fm["status"] = status

    # Re-serialize frontmatter
    new_fm = yaml.dump(fm, default_flow_style=False, sort_keys=False).strip()
    new_text = f"---\n{new_fm}\n---\n\n{body}\n"
    path.write_text(new_text)
