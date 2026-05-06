"""Unified DAG of all planned steps across iterations for a single goal."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from soothe.core.agent_loop.state.schemas import PlanResult, StepResult

logger = logging.getLogger(__name__)


@dataclass
class PlanNode:
    """A single step node in the goal-level DAG."""

    composite_id: str
    description: str
    plan_id: str
    plan_iteration: int
    status: Literal["pending", "completed", "failed"] = "pending"
    dependencies: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    subagent: str | None = None
    outcome: StepResult | None = None


@dataclass
class PlanDAG:
    """Unified DAG representation for all planned steps across iterations.

    Steps from all plans (including replans) are merged into a single DAG.
    Each node is keyed by its composite step ID (e.g., "KFA-01").
    """

    nodes: dict[str, PlanNode] = field(default_factory=dict)
    _plan_ids: set[str] = field(default_factory=set)

    def ingest_plan(self, plan_result: PlanResult, plan_id: str | None, iteration: int) -> None:
        """Add all steps from a PlanResult into the DAG.

        When plan_action='new', all steps are new nodes.
        When plan_action='keep', no new steps are added (the decision is reused).
        """
        decision = plan_result.decision
        if decision is None:
            return

        if plan_id is not None:
            self._plan_ids.add(plan_id)

        for step in decision.steps:
            cid = step.id
            if cid in self.nodes:
                # Node already exists (e.g., from a keep plan); update if needed
                existing = self.nodes[cid]
                if existing.status == "pending":
                    # Refresh dependencies if this is a replan
                    if step.dependencies:
                        existing.dependencies = list(step.dependencies)
                    if step.evidence_refs:
                        existing.evidence_refs = list(step.evidence_refs)
                    if step.subagent:
                        existing.subagent = step.subagent
                continue

            deps = list(step.dependencies) if step.dependencies else []
            self.nodes[cid] = PlanNode(
                composite_id=cid,
                description=step.description,
                plan_id=plan_id or "unknown",
                plan_iteration=iteration,
                dependencies=deps,
                evidence_refs=list(step.evidence_refs) if step.evidence_refs else [],
                subagent=step.subagent,
            )

        logger.debug(
            "[PlanDAG] ingested plan: plan_id=%s iter=%d nodes=%d total=%d",
            plan_id,
            iteration,
            len(decision.steps),
            len(self.nodes),
        )

    def mark_completed(self, step_id: str, outcome: StepResult) -> None:
        node = self.nodes.get(step_id)
        if node is not None:
            node.status = "completed"
            node.outcome = outcome

    def mark_failed(self, step_id: str, outcome: StepResult) -> None:
        node = self.nodes.get(step_id)
        if node is not None:
            node.status = "failed"
            node.outcome = outcome

    # --- Read-only properties ---

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
    def remaining_steps(self) -> int:
        return sum(1 for n in self.nodes.values() if n.status == "pending")

    @property
    def has_dag_dependencies(self) -> bool:
        return any(n.dependencies for n in self.nodes.values())

    @property
    def max_chain_depth(self) -> int:
        """Longest dependency chain in the DAG (BFS-based depth calculation)."""
        if not self.nodes:
            return 0

        # Build adjacency: node -> nodes that depend on it
        dependents: dict[str, list[str]] = {cid: [] for cid in self.nodes}
        in_degree: dict[str, int] = {cid: 0 for cid in self.nodes}
        for cid, node in self.nodes.items():
            for dep in node.dependencies:
                if dep in dependents:
                    dependents[dep].append(cid)
                    in_degree[cid] += 1

        # BFS from roots (nodes with no dependencies)
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
    def plan_count(self) -> int:
        return len(self._plan_ids)

    @property
    def success_rate(self) -> float:
        executed = self.completed_steps + self.failed_steps
        if executed == 0:
            return 1.0
        return self.completed_steps / executed

    @property
    def used_subagents(self) -> bool:
        return any(n.subagent for n in self.nodes.values())

    def get_completed_step_ids(self) -> set[str]:
        return {cid for cid, n in self.nodes.items() if n.status == "completed"}

    def get_remaining_step_ids(self) -> set[str]:
        return {cid for cid, n in self.nodes.items() if n.status == "pending"}

    @property
    def pending_step_ids(self) -> set[str]:
        """Step IDs that are still pending (not yet executed)."""
        return {cid for cid, n in self.nodes.items() if n.status == "pending"}

    @property
    def failed_step_ids(self) -> set[str]:
        """Step IDs that have failed execution."""
        return {cid for cid, n in self.nodes.items() if n.status == "failed"}

    @property
    def ready_step_ids(self) -> set[str]:
        """Pending steps whose dependencies are all satisfied (ready to execute)."""
        completed = self.get_completed_step_ids()
        ready: set[str] = set()
        for cid, node in self.nodes.items():
            if node.status != "pending":
                continue
            if all(dep in completed for dep in node.dependencies):
                ready.add(cid)
        return ready
