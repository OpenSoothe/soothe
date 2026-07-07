"""Data models for the Context Engine (RFC-624, RFC-625)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from soothe.foundation.context.dag_utils import expand_dependency_satisfaction_ids

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
BLOCKED_STATES: frozenset[str] = frozenset({"awaiting_clarification", "suspended"})

StepStatus = Literal["pending", "completed", "failed", "skipped"]

MAX_GOAL_DEPTH = 5


# ── Evidence ledger ───────────────────────────────────────────────────────


class EvidenceEntry(BaseModel):
    """Evidence row for plan validation (RFC-220).

    Reused from loop/state/schemas.py for GoalNode.evidence_ledger field
    in RFC-624 Phase 4 Step 4 consolidation.

    Attributes:
        evidence_id: Stable id for the evidence ledger.
        summary: Compact summary for prompts and validation.
        kind: Provenance classification.
    """

    evidence_id: str
    summary: str = ""
    kind: Literal["tool", "bootstrap", "ledger"] = "bootstrap"


# ── Execution record ────────────────────────────────────────────────────


class StepExecution(BaseModel):
    """Record of CoreAgent execution for a step."""

    input_messages: list[dict[str, Any]] = Field(default_factory=list)
    output_messages: list[dict[str, Any]] = Field(default_factory=list)
    tokens_used: int = 0
    duration_ms: int = 0
    error: str | None = None
    error_type: str | None = None
    thread_id: str | None = None
    outcome: dict[str, Any] | None = None
    tool_call_count: int = 0
    subagent_task_completions: int = 0
    hit_subagent_cap: bool = False
    hit_tool_budget: bool = False


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
        satisfied = expand_dependency_satisfaction_ids(self.completed_step_ids())
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

        satisfied = expand_dependency_satisfaction_ids(self.completed_step_ids())

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
    """Single goal in the unified Goal+Step DAG (RFC-624, RFC-625).

    Migrated fields from Goal model (autopilot/engine/models.py) per RFC-625:
    - retry_count, max_retries, send_back_count, max_send_backs (RFC-204)
    - source_file, workspace, attempts_after_crash (RFC-222)
    - pending_clarification (RFC-622)
    - guidance_accumulated (RFC-228)
    - report (GoalReport on completion)

    New dreaming fields per RFC-625:
    - topic, findings, distilled
    """

    # Core identity
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str
    priority: int = 50
    status: GoalStatus = "pending"

    # DAG relationships
    parent_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    informs: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)

    # Embedded step DAG
    steps: StepDAG = Field(default_factory=StepDAG)

    # Lineage
    generating_reasoning: str | None = None
    source: Literal["user", "directive", "file_discovery", "decomposition"] = "user"

    # Execution tracking (RFC-624 Phase 4 Step 4)
    iteration_count: int = 0  # Current iteration number for this goal
    total_tokens_used: int = 0
    total_duration_ms: int = 0
    max_iterations: int = 0
    thread_id: str | None = None
    assigned_loop_id: str | None = None
    previous_plan: dict[str, Any] | None = None
    action_history: list[str] = Field(default_factory=list)
    evidence_ledger: list[EvidenceEntry] = Field(
        default_factory=list,
        description="Append-only evidence ids for plan validation.",
    )

    # Retry/backoff (from Goal, RFC-204)
    retry_count: int = 0
    max_retries: int = 2
    send_back_count: int = 0  # Consensus send-backs
    max_send_backs: int = 3
    attempts_after_crash: int = 0  # RFC-222 H4

    # Workspace/source (from Goal, RFC-222)
    source_file: str | None = None  # GOAL.md path if file-sourced
    workspace: str | None = None  # Autopilot dispatch workspace

    # Completion/completion state (from Goal)
    # report is serialized GoalReport (avoid circular import)
    report: dict[str, Any] | None = None  # Serialized GoalReport on completion
    error: str | None = None  # Failure reason if status == "failed"
    pending_clarification: dict[str, Any] | None = None  # RFC-622

    # Guidance (from Goal, RFC-228)
    guidance_accumulated: list[dict[str, Any]] = Field(default_factory=list)

    # Cron job tracking (RFC-229)
    cron_job_id: str | None = None  # Cron job that spawned this goal (for recurring rescheduling)

    # Dreaming (NEW, RFC-625)
    # Dreaming (NEW, RFC-625)
    topic: str | None = None  # Topic tag for cross-loop dreaming
    findings: list[str] = Field(default_factory=list)  # Key findings from execution
    distilled: bool = False  # Whether goal has been distilled

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Plan-assess audit (IG-557; not replayed into assess prompts except Phase C inline)
    last_assessment: dict[str, Any] | None = None
    last_assessment_iteration: int | None = None

    def touch(self) -> None:
        """Update updated_at timestamp."""
        self.updated_at = datetime.now(UTC)


class GoalStepDAGSnapshot(BaseModel):
    """Serializable snapshot of the full GoalStepDAG for persistence."""

    goals: list[GoalNode] = Field(default_factory=list)
    saved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GoalStepDAG(BaseModel):
    """Top-level DAG of goals, each containing nested step DAGs."""

    goals: dict[str, GoalNode] = Field(default_factory=dict)

    # ── Goal lifecycle ──────────────────────────────────────────

    def add_goal(self, goal: GoalNode) -> None:
        """Add a goal to the DAG. Validates parent exists and depth limit."""
        if goal.parent_id:
            parent = self.goals.get(goal.parent_id)
            if parent is None:
                msg = f"Parent goal {goal.parent_id} not found."
                raise ValueError(msg)
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
            goal.error = error
            goal.updated_at = datetime.now(UTC)

    def suspend_goal(self, goal_id: str, reason: str) -> None:
        goal = self.goals.get(goal_id)
        if goal is not None:
            goal.status = "suspended"
            goal.assigned_loop_id = None
            goal.updated_at = datetime.now(UTC)

    def cancel_goal(self, goal_id: str) -> None:
        """Transition goal to cancelled (terminal state)."""
        goal = self.goals.get(goal_id)
        if goal is not None:
            goal.status = "cancelled"
            goal.updated_at = datetime.now(UTC)

    def block_goal(self, goal_id: str) -> None:
        """Transition goal to blocked."""
        goal = self.goals.get(goal_id)
        if goal is not None:
            goal.status = "blocked"
            goal.updated_at = datetime.now(UTC)

    def unblock_goal(self, goal_id: str) -> None:
        """Transition goal from blocked back to pending."""
        goal = self.goals.get(goal_id)
        if goal is not None and goal.status == "blocked":
            goal.status = "pending"
            goal.updated_at = datetime.now(UTC)

    # ── Scheduling ──────────────────────────────────────────────

    def peek_ready_goals(self, limit: int = 1) -> list[GoalNode]:
        """Return ready candidates without mutation (read-only, RFC-625).

        Mirrors GoalEngine._filter_ready_candidates: filters by
        status == "pending", checks hard dependencies (all in
        TERMINAL_STATES), checks conflicts_with (no active goal).
        """
        active_ids = {gid for gid, g in self.goals.items() if g.status == "active"}
        ready: list[GoalNode] = []
        for goal in self.goals.values():
            if goal.status != "pending":
                continue
            # RFC-622: also skip goals in BLOCKED_STATES
            if goal.status in BLOCKED_STATES:
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

    def claim_goal(self, goal_id: str, loop_id: str | None = None) -> GoalNode | None:
        """Atomically transition goal to active (RFC-222, RFC-625).

        Re-checks conflicts and dependencies at claim time to prevent race conditions.
        Returns the goal if claimed, None if ineligible, conflict appeared, or deps unmet.
        """
        goal = self.goals.get(goal_id)
        if goal is None or goal.status != "pending":
            return None
        # Re-check conflicts at claim time
        active_ids = {
            gid for gid, g in self.goals.items() if g.status == "active" and gid != goal_id
        }
        if any(dep_id in active_ids for dep_id in goal.conflicts_with):
            logger.debug("Goal %s claim aborted: conflict appeared", goal_id)
            return None
        # Re-check dependencies at claim time
        deps_met = all(
            (dep := self.goals.get(dep_id)) is not None and dep.status in TERMINAL_STATES
            for dep_id in goal.depends_on
        )
        if not deps_met:
            logger.debug("Goal %s claim aborted: dependencies unmet", goal_id)
            return None
        goal.status = "active"
        goal.updated_at = datetime.now(UTC)
        if loop_id:
            goal.assigned_loop_id = loop_id
        logger.debug("Claimed goal %s (loop_id=%s)", goal_id, loop_id)
        return goal

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

    # ── RFC-625: Monitor-required methods ──────────────────────────────

    def remove_goal(self, goal_id: str) -> bool:
        """Remove a goal from the DAG. Validates no dependents.

        Returns True if removed, False if goal not found or has dependents.
        """
        goal = self.goals.get(goal_id)
        if goal is None:
            return False

        # Check if any goal depends on this one
        dependents = self.get_goal_dependents(goal_id)
        if dependents:
            logger.warning(
                "Cannot remove goal %s: has dependents %s",
                goal_id,
                dependents,
            )
            return False

        del self.goals[goal_id]
        logger.info("Removed goal %s from DAG", goal_id)
        return True

    def merge_goals(
        self, goal_ids: list[str], merged_description: str, merged_id: str | None = None
    ) -> GoalNode | None:
        """Merge multiple goals into a single consolidated goal.

        Preserves union of dependencies, informs, and findings.
        Returns new merged goal, or None if any goal not found.
        """
        goals_to_merge = [self.goals.get(gid) for gid in goal_ids]
        if not all(goals_to_merge):
            logger.warning("Cannot merge: some goals not found")
            return None

        # Collect union of dependencies and informs
        merged_depends_on: set[str] = set()
        merged_informs: set[str] = set()
        merged_findings: list[str] = []
        merged_priority = max(g.priority for g in goals_to_merge)

        for g in goals_to_merge:
            merged_depends_on.update(g.depends_on)
            merged_informs.update(g.informs)
            merged_findings.extend(g.findings)
            # Remove self-references
            merged_depends_on.difference_update(goal_ids)
            merged_informs.difference_update(goal_ids)

        merged = GoalNode(
            id=merged_id or uuid.uuid4().hex[:8],
            description=merged_description,
            priority=merged_priority,
            status="pending",
            depends_on=list(merged_depends_on),
            informs=list(merged_informs),
            findings=merged_findings,
            source="decomposition",
            generating_reasoning=f"Merged from goals: {', '.join(goal_ids)}",
        )

        # Remove old goals (they have no dependents by construction)
        for gid in goal_ids:
            self.goals.pop(gid, None)

        self.goals[merged.id] = merged
        logger.info("Merged goals %s → %s", goal_ids, merged.id)
        return merged

    def is_dag_complete(self) -> bool:
        """Check if all goals in DAG are in terminal states."""
        if not self.goals:
            return True
        return all(g.status in TERMINAL_STATES for g in self.goals.values())

    def get_goals_by_status(self, status: GoalStatus | None = None) -> list[GoalNode]:
        """Filter goals by status (None = all goals)."""
        if status is None:
            return list(self.goals.values())
        return [g for g in self.goals.values() if g.status == status]

    def get_goal_dependents(self, goal_id: str) -> list[str]:
        """Get all goal IDs that depend on this goal."""
        dependents: list[str] = []
        for gid, g in self.goals.items():
            if goal_id in g.depends_on:
                dependents.append(gid)
        return dependents

    def update_dependencies(self, goal_id: str, depends_on: list[str]) -> bool:
        """Update goal dependencies (for mode switch flattening).

        Returns True if updated, False if goal not found.
        """
        goal = self.goals.get(goal_id)
        if goal is None:
            return False
        goal.depends_on = depends_on
        goal.touch()
        return True

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


# ── Dreaming models (RFC-625) ────────────────────────────────────────────────


class EpisodeSummary(BaseModel):
    """Distilled episodic memory from goal execution (RFC-625 dreaming).

    Created by DreamingCoordinator.episodic mode, stored in ContextEngine
    episodic memory store.
    """

    goal_id: str = Field(description="Source goal ID")
    description: str = Field(description="Goal description")
    outcome_summary: str = Field(description="Outcome summary")
    key_steps: list[str] = Field(default_factory=list, description="Key steps executed")
    lessons_learned: str = Field(default="", description="Lessons learned")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
