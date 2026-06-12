"""Data models for the Context Engine (RFC-624)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Status types ────────────────────────────────────────────────────────

GoalStatus = Literal[
    "pending",
    "active",
    "completed",
    "failed",
    "suspended",
    "blocked",
    "validated",
    "awaiting_clarification",
    "cancelled",
]

TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

StepStatus = Literal["pending", "completed", "failed", "skipped"]

MAX_GOAL_DEPTH = 5


# ── Execution record ────────────────────────────────────────────────────


class StepExecution(BaseModel):
    """Record of CoreAgent execution for a step."""

    input_messages: list[dict[str, Any]] = Field(default_factory=list)
    output_messages: list[dict[str, Any]] = Field(default_factory=list)
    tokens_used: int = 0
    duration_ms: int = 0
    error: str | None = None
    thread_id: str | None = None


# ── Step DAG ────────────────────────────────────────────────────────────


class StepNode(BaseModel):
    """Single step within a goal's step DAG."""

    id: str
    description: str
    status: StepStatus = "pending"
    dependencies: list[str] = Field(default_factory=list)
    plan_iteration: int = 0
    reasoning_trace: str | None = None
    execution: StepExecution | None = None


def _expand_dependency_satisfaction_ids(completed_step_ids: set[str]) -> set[str]:
    """Expand completed step ids with unambiguous local numeric suffix aliases.

    Mirrors ``expand_dependency_satisfaction_ids`` from
    ``loop/planning/dependency_tokens.py``. When a composite id like ``KFA-01``
    is completed, later plans may reference it as ``01`` or ``1``. This adds
    those aliases only when unambiguous.
    """
    base = set(completed_step_ids)
    if not base:
        return base

    value_to_owners: dict[int, list[str]] = {}
    for sid in base:
        if "-" not in sid:
            continue
        tail = sid.rsplit("-", 1)[-1]
        if not tail.isdigit():
            continue
        value_to_owners.setdefault(int(tail, 10), []).append(sid)

    for owners in value_to_owners.values():
        if len(owners) != 1:
            continue
        own = owners[0]
        tail = own.rsplit("-", 1)[-1]
        base.add(tail)
        base.add(str(int(tail, 10)))
    return base


class StepDAG(BaseModel):
    """DAG of steps for a single goal."""

    nodes: dict[str, StepNode] = Field(default_factory=dict)

    def add_step(self, step: StepNode) -> None:
        """Add a step node to the DAG."""
        self.nodes[step.id] = step

    def ready_steps(self) -> set[str]:
        """Pending steps whose dependencies are all satisfied.

        Uses dependency token expansion to resolve composite step IDs
        and their local numeric aliases.
        """
        satisfied = _expand_dependency_satisfaction_ids(self.completed_step_ids())
        ready: set[str] = set()
        for cid, node in self.nodes.items():
            if node.status != "pending":
                continue
            if all(dep in satisfied for dep in node.dependencies):
                ready.add(cid)
        return ready

    def completed_step_ids(self) -> set[str]:
        return {cid for cid, n in self.nodes.items() if n.status == "completed"}

    def failed_step_ids(self) -> set[str]:
        return {cid for cid, n in self.nodes.items() if n.status == "failed"}

    def pending_step_ids(self) -> set[str]:
        return {cid for cid, n in self.nodes.items() if n.status == "pending"}

    def mark_completed(self, step_id: str, execution: StepExecution) -> None:
        node = self.nodes.get(step_id)
        if node is not None:
            node.status = "completed"
            node.execution = execution

    def mark_failed(self, step_id: str, execution: StepExecution) -> None:
        node = self.nodes.get(step_id)
        if node is not None:
            node.status = "failed"
            node.execution = execution

    def mark_skipped(self, step_id: str) -> None:
        node = self.nodes.get(step_id)
        if node is not None:
            node.status = "skipped"

    @property
    def chain_depth(self) -> int:
        """Longest dependency chain in the DAG (BFS, same as PlanDAG.max_chain_depth)."""
        if not self.nodes:
            return 0

        satisfied = _expand_dependency_satisfaction_ids(self.completed_step_ids())

        dependents: dict[str, list[str]] = {cid: [] for cid in self.nodes}
        in_degree: dict[str, int] = {cid: 0 for cid in self.nodes}
        for cid, node in self.nodes.items():
            for dep in node.dependencies:
                if dep in satisfied:
                    continue
                if dep in dependents:
                    dependents[dep].append(cid)
                    in_degree[cid] += 1

        from collections import deque

        depth: dict[str, int] = {cid: 1 for cid in self.nodes}
        queue = deque(cid for cid, deg in in_degree.items() if deg == 0)
        max_depth = 1

        while queue:
            current = queue.popleft()
            current_depth = depth[current]
            max_depth = max(max_depth, current_depth)
            for dep in dependents[current]:
                depth[dep] = max(depth[dep], current_depth + 1)
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        return max_depth

    @property
    def total_steps(self) -> int:
        return len(self.nodes)

    @property
    def completed_steps(self) -> int:
        return sum(1 for n in self.nodes.values() if n.status == "completed")

    @property
    def failed_steps(self) -> int:
        return sum(1 for n in self.nodes.values() if n.status == "failed")

    @property
    def success_rate(self) -> float:
        executed = self.completed_steps + self.failed_steps
        if executed == 0:
            return 1.0
        return self.completed_steps / executed


# ── Goal DAG ────────────────────────────────────────────────────────────


class GoalNode(BaseModel):
    """Single goal in the unified Goal+Step DAG."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str
    priority: int = 50
    status: GoalStatus = "pending"

    parent_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    informs: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)

    steps: StepDAG = Field(default_factory=StepDAG)

    generating_reasoning: str | None = None
    source: Literal["user", "directive", "file_discovery", "decomposition"] = "user"

    total_tokens_used: int = 0
    thread_id: str | None = None
    assigned_loop_id: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GoalStepDAGSnapshot(BaseModel):
    """Serializable snapshot of the full GoalStepDAG for persistence."""

    goals: list[GoalNode] = Field(default_factory=list)
    saved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GoalStepDAG(BaseModel):
    """Top-level DAG of goals, each containing nested step DAGs."""

    goals: dict[str, GoalNode] = Field(default_factory=dict)

    # ── Goal lifecycle ──────────────────────────────────────────

    def add_goal(self, goal: GoalNode) -> None:
        """Add a goal to the DAG. Validates depth limit."""
        if goal.parent_id:
            depth = self._goal_depth(goal.parent_id)
            if depth >= MAX_GOAL_DEPTH:
                msg = f"Goal depth limit ({MAX_GOAL_DEPTH}) exceeded. Parent {goal.parent_id} is at depth {depth}."
                raise ValueError(msg)
        self.goals[goal.id] = goal

    def get_goal(self, goal_id: str) -> GoalNode | None:
        return self.goals.get(goal_id)

    def complete_goal(self, goal_id: str) -> None:
        goal = self.goals.get(goal_id)
        if goal is not None:
            goal.status = "completed"
            goal.updated_at = datetime.now(UTC)

    def fail_goal(self, goal_id: str, error: str) -> None:
        goal = self.goals.get(goal_id)
        if goal is not None:
            goal.status = "failed"
            goal.updated_at = datetime.now(UTC)

    def suspend_goal(self, goal_id: str, reason: str) -> None:
        goal = self.goals.get(goal_id)
        if goal is not None:
            goal.status = "suspended"
            goal.assigned_loop_id = None
            goal.updated_at = datetime.now(UTC)

    # ── Scheduling ──────────────────────────────────────────────

    def ready_goals(self, limit: int = 1) -> list[GoalNode]:
        """Goals whose deps are satisfied, sorted by priority desc / created_at asc.

        Mirrors GoalEngine._filter_ready_candidates: filters by
        status == "pending", checks hard dependencies (all in
        TERMINAL_STATES), checks conflicts_with (no active goal).
        """
        active_ids = {gid for gid, g in self.goals.items() if g.status == "active"}
        ready: list[GoalNode] = []
        for goal in self.goals.values():
            if goal.status != "pending":
                continue
            deps_met = all(
                (dep := self.goals.get(dep_id)) is not None and dep.status in TERMINAL_STATES
                for dep_id in goal.depends_on
            )
            if not deps_met:
                continue
            has_conflict = any(dep_id in active_ids for dep_id in goal.conflicts_with)
            if has_conflict:
                continue
            ready.append(goal)
        ready.sort(key=lambda g: (-g.priority, g.created_at))
        return ready[:limit]

    def active_goals(self) -> list[GoalNode]:
        return [g for g in self.goals.values() if g.status == "active"]

    # ── Lineage ─────────────────────────────────────────────────

    def goal_lineage(self, goal_id: str) -> list[str]:
        """Return chain of goal descriptions from root to this goal."""
        chain: list[str] = []
        current_id: str | None = goal_id
        visited: set[str] = set()
        while current_id:
            if current_id in visited:
                break
            visited.add(current_id)
            goal = self.goals.get(current_id)
            if goal is None:
                break
            chain.append(goal.description)
            current_id = goal.parent_id
        chain.reverse()
        return chain

    # ── Snapshot ────────────────────────────────────────────────

    def snapshot(self) -> GoalStepDAGSnapshot:
        return GoalStepDAGSnapshot(goals=list(self.goals.values()))

    def restore_from_snapshot(self, snapshot: GoalStepDAGSnapshot) -> None:
        self.goals.clear()
        for goal in snapshot.goals:
            self.goals[goal.id] = goal

    # ── Recovery ────────────────────────────────────────────────

    def recover_active_goals(self) -> list[str]:
        """Reset goals stuck in 'active' to 'pending' (crash recovery)."""
        recovered: list[str] = []
        now = datetime.now(UTC)
        for goal in self.goals.values():
            if goal.status != "active":
                continue
            goal.assigned_loop_id = None
            goal.status = "pending"
            goal.updated_at = now
            recovered.append(goal.id)
            logger.warning(
                "Crash recovery: reset goal %s → pending",
                goal.id,
            )
        return recovered

    # ── Internal helpers ────────────────────────────────────────

    def _goal_depth(self, goal_id: str) -> int:
        depth = 0
        current_id: str | None = goal_id
        visited: set[str] = set()
        while current_id:
            if current_id in visited:
                break
            visited.add(current_id)
            goal = self.goals.get(current_id)
            if goal is None:
                break
            depth += 1
            current_id = goal.parent_id
            if depth > MAX_GOAL_DEPTH + 1:
                break
        return depth
