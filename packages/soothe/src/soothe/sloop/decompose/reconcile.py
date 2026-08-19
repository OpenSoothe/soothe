"""Deterministic CE reconcile for DecompositionProposal batches (RFC-904 / IG-751 P2).

LLM-assisted semantic dedup / cross-subtree inference is P4. This module always
runs exact dedup, branch/depth/step budgets, ID assignment, and commit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe.context.decomposition import DecompositionProposal, ProposedSubtask
from soothe.context.models import StepNode
from soothe.sloop.state.schemas import allocate_plan_id, composite_step_id

if TYPE_CHECKING:
    from soothe.config.models import DecomposeLoopConfig
    from soothe.context.engine import ContextEngine
    from soothe.context.models import StepDAG

logger = logging.getLogger(__name__)


def normalize_subtask_key(description: str) -> str:
    """Normalize description for exact-dedup matching."""
    return " ".join((description or "").lower().split())


@dataclass
class ReconcileRejection:
    """A proposal (or parent) rejected during reconcile."""

    parent_step_id: str
    reason: str


@dataclass
class ReconcileResult:
    """Outcome of a deterministic reconcile pass."""

    committed_step_ids: list[str] = field(default_factory=list)
    decomposed_parent_ids: list[str] = field(default_factory=list)
    rejected: list[ReconcileRejection] = field(default_factory=list)
    plan_id: str | None = None
    llm_used: bool = False


def _branch_cap(parent_step_id: str, dag: StepDAG, cfg: DecomposeLoopConfig) -> int:
    parent = dag.nodes.get(parent_step_id)
    if parent is None or parent.parent_step_id is None:
        return cfg.max_branch_root
    return cfg.max_branch_inner


def _next_local_ids(n: int) -> list[str]:
    """Allocate ``01``..``n`` zero-padded to at least 2 digits."""
    width = max(2, len(str(n)))
    return [f"{i:0{width}d}" for i in range(1, n + 1)]


def _drop_new_node_cycles(nodes: list[StepNode]) -> None:
    """Drop in-batch dependency edges that participate in a cycle (mutates nodes)."""
    id_set = {n.id for n in nodes}
    deps_map = {n.id: [d for d in n.dependencies if d in id_set] for n in nodes}
    to_remove: set[tuple[str, str]] = set()
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting or step_id in visited:
            return
        visiting.add(step_id)
        for dep in deps_map.get(step_id, []):
            if dep in visiting:
                to_remove.add((dep, step_id))
                continue
            visit(dep)
        visiting.remove(step_id)
        visited.add(step_id)

    for sid in id_set:
        visit(sid)

    if not to_remove:
        return

    logger.warning("Decomposition dependency cycle detected; dropping cyclic edges")
    for node in nodes:
        node.dependencies = [d for d in node.dependencies if (d, node.id) not in to_remove]


def plan_commit_from_proposals(
    dag: StepDAG,
    proposals: list[DecompositionProposal],
    *,
    config: DecomposeLoopConfig,
    plan_id: str | None = None,
) -> tuple[list[StepNode], list[str], list[ReconcileRejection], str]:
    """Build StepNodes to commit without mutating ``dag``.

    Returns:
        ``(new_nodes, parents_to_mark_decomposed, rejections, plan_id)``.
    """
    rejections: list[ReconcileRejection] = []
    if not proposals:
        return [], [], [], plan_id or allocate_plan_id()

    scoped_plan_id = plan_id or allocate_plan_id()
    ordered = sorted(proposals, key=lambda p: (p.wave_seq, p.parent_step_id))

    accepted: list[tuple[str, list[ProposedSubtask]]] = []
    for prop in ordered:
        parent_id = prop.parent_step_id
        parent = dag.nodes.get(parent_id)
        if parent is None:
            rejections.append(ReconcileRejection(parent_id, "parent_not_found"))
            continue
        if parent.status in ("completed", "failed", "skipped", "superseded"):
            rejections.append(ReconcileRejection(parent_id, f"parent_status_{parent.status}"))
            continue
        depth = dag.lineage_depth(parent_id)
        if depth >= config.max_depth:
            rejections.append(ReconcileRejection(parent_id, "max_depth_exceeded"))
            continue
        cap = _branch_cap(parent_id, dag, config)
        if len(prop.subtasks) > cap:
            rejections.append(ReconcileRejection(parent_id, "branch_cap_exceeded"))
            continue
        accepted.append((parent_id, list(prop.subtasks)))

    if not accepted:
        return [], [], rejections, scoped_plan_id

    # Exact dedup: first occurrence wins as primary; later same-key → secondary.
    merged: dict[str, tuple[str, list[str], ProposedSubtask, list[int] | None]] = {}
    parent_local_keys: dict[str, list[str]] = {}

    for parent_id, subtasks in accepted:
        keys_for_parent: list[str] = []
        for sub in subtasks:
            key = normalize_subtask_key(sub.description)
            keys_for_parent.append(key)
            if key in merged:
                primary, secondaries, kept, _deps = merged[key]
                if parent_id != primary and parent_id not in secondaries:
                    secondaries.append(parent_id)
                # Drop local deps once a node is shared across parents.
                merged[key] = (primary, secondaries, kept, None)
            else:
                merged[key] = (parent_id, [], sub, sub.depends_on_local)
        parent_local_keys[parent_id] = keys_for_parent

    if len(dag.nodes) + len(merged) > config.max_steps:
        for parent_id, _ in accepted:
            rejections.append(ReconcileRejection(parent_id, "max_steps_exceeded"))
        return [], [], rejections, scoped_plan_id

    keys_ordered = sorted(merged.keys())
    local_ids = _next_local_ids(len(keys_ordered))
    key_to_composite: dict[str, str] = {
        key: composite_step_id(local, scoped_plan_id)
        for key, local in zip(keys_ordered, local_ids, strict=True)
    }

    new_nodes: list[StepNode] = []
    parents_to_decompose: set[str] = set()

    for key in keys_ordered:
        primary, secondaries, sub, deps_local = merged[key]
        parents_to_decompose.add(primary)
        parents_to_decompose.update(secondaries)

        dependencies: list[str] = []
        if deps_local and primary in parent_local_keys:
            local_keys = parent_local_keys[primary]
            for idx in deps_local:
                if 0 <= idx < len(local_keys):
                    dep_key = local_keys[idx]
                    dep_id = key_to_composite.get(dep_key)
                    if dep_id and dep_id != key_to_composite[key]:
                        dependencies.append(dep_id)

        dependencies = list(dict.fromkeys(dependencies))
        # Keep only edges resolvable in this batch or already on the DAG.
        dependencies = [d for d in dependencies if d in key_to_composite.values() or d in dag.nodes]

        node = StepNode(
            id=key_to_composite[key],
            description=sub.description,
            full_description=sub.full_description or None,
            expected_output=sub.expected_output or None,
            execution_hint=sub.execution_hint,
            dependencies=dependencies,
            parent_step_id=primary,
            secondary_parent_step_ids=list(secondaries),
            status="pending",
        )
        new_nodes.append(node)

    _drop_new_node_cycles(new_nodes)
    return new_nodes, sorted(parents_to_decompose), rejections, scoped_plan_id


async def reconcile_proposals_deterministic(
    ce: ContextEngine,
    goal_id: str,
    proposals: list[DecompositionProposal],
    *,
    config: DecomposeLoopConfig,
    plan_id: str | None = None,
) -> ReconcileResult:
    """Commit proposal children onto the goal StepDAG and mark parents decomposed."""
    goal = await ce.get_goal(goal_id)
    if goal is None:
        return ReconcileResult(
            rejected=[ReconcileRejection("*", f"goal_not_found:{goal_id}")],
        )

    new_nodes, parents, rejections, scoped_plan_id = plan_commit_from_proposals(
        goal.steps,
        proposals,
        config=config,
        plan_id=plan_id,
    )
    if not new_nodes:
        return ReconcileResult(rejected=rejections, plan_id=scoped_plan_id)

    plan_iteration = 0
    for pid in parents:
        parent = goal.steps.nodes.get(pid)
        if parent is not None:
            plan_iteration = max(plan_iteration, parent.plan_iteration)

    await ce.add_steps(goal_id, new_nodes, plan_iteration=plan_iteration)
    for pid in parents:
        if pid in goal.steps.nodes:
            goal.steps.mark_decomposed(pid)
    goal.updated_at = datetime.now(UTC)

    logger.info(
        "Reconcile committed %d steps for goal %s (parents=%s, rejected=%d)",
        len(new_nodes),
        goal_id,
        parents,
        len(rejections),
    )
    return ReconcileResult(
        committed_step_ids=[n.id for n in new_nodes],
        decomposed_parent_ids=parents,
        rejected=rejections,
        plan_id=scoped_plan_id,
        llm_used=False,
    )


def drain_executor_proposals(executor: Any) -> list[DecompositionProposal]:
    """Drain proposals queued on an Executor (P1 sink)."""
    raw = getattr(executor, "decompose_proposals", None)
    if not isinstance(raw, list) or not raw:
        return []
    out = list(raw)
    raw.clear()
    return out
