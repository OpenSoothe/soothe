"""Validate and normalize plan step dependency DAGs across plan waves."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from soothe.context.dag_utils import expand_dependency_satisfaction_ids
from soothe.sloop.state.schemas import AgentDecision, StepAction

logger = logging.getLogger(__name__)


def _canonical_completed_ref(dep: str, completed_ids: set[str]) -> str | None:
    """Map a dependency token to a canonical completed composite id when unambiguous."""
    d = dep.strip()
    if not d:
        return None
    if d in completed_ids:
        return d

    expanded = expand_dependency_satisfaction_ids(completed_ids)
    if d not in expanded:
        return None

    if d in completed_ids:
        return d

    if d.isdigit():
        value = int(d, 10)
        matches = [
            cid
            for cid in completed_ids
            if "-" in cid
            and cid.rsplit("-", 1)[-1].isdigit()
            and int(cid.rsplit("-", 1)[-1], 10) == value
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            logger.warning(
                "Ambiguous cross-wave dependency %r matches %s; leaving unchanged",
                d,
                matches,
            )
            return d

    return d if d in expanded else None


def _resolve_dependency_ref(
    dep: str,
    *,
    completed_ids: set[str],
    in_plan_ids: set[str],
) -> str | None:
    """Resolve one dependency string to a valid in-plan or completed target."""
    d = dep.strip()
    if not d:
        return None
    if d in in_plan_ids:
        return d
    canonical = _canonical_completed_ref(d, completed_ids)
    if canonical is not None:
        return canonical
    return None


def _infer_linear_dependencies_when_mode_dependency(
    steps: list[StepAction],
    *,
    execution_mode: str,
) -> tuple[list[StepAction], bool]:
    """Fill missing in-wave edges when planner chose dependency mode.

    Models often set ``execution_mode`` to ``dependency`` while omitting
    ``dependencies`` on some downstream steps. Each step without deps (after the
    first) is chained to its list-order predecessor so diagnose→fix→verify
    pipelines stay sequential instead of running in parallel.
    """
    if execution_mode != "dependency" or len(steps) < 2:
        return steps, False

    updated: list[StepAction] = []
    changed = False
    for i, step in enumerate(steps):
        if i == 0 or step.dependencies:
            updated.append(step)
            continue
        updated.append(step.model_copy(update={"dependencies": [steps[i - 1].id]}))
        changed = True

    if changed:
        filled = sum(1 for s in updated[1:] if s.dependencies)
        logger.info(
            "Plan dependency mode missing edges; filled %d/%d downstream step(s) "
            "with list-order predecessors",
            filled,
            len(steps) - 1,
        )
    return updated, changed


def _drop_in_plan_cycles(steps: list[StepAction]) -> list[StepAction]:
    """Remove in-plan dependency edges that participate in a cycle."""
    id_set = {s.id for s in steps}
    deps_map = {s.id: [d for d in (s.dependencies or []) if d in id_set] for s in steps}
    to_remove: set[tuple[str, str]] = set()
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            return
        if step_id in visited:
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
        return steps

    logger.warning("In-plan dependency cycle detected; dropping cyclic edges")
    updated: list[StepAction] = []
    for step in steps:
        deps = step.dependencies or []
        filtered = [d for d in deps if (d, step.id) not in to_remove]
        if filtered != deps:
            updated.append(step.model_copy(update={"dependencies": filtered or None}))
        else:
            updated.append(step)
    return updated


def normalize_plan_dag(
    decision: AgentDecision,
    *,
    completed_ids: Iterable[str],
) -> AgentDecision:
    """Normalize dependency refs, drop invalid targets, and enforce dependency mode.

    Args:
        decision: Parsed execution decision from plan-generate.
        completed_ids: Completed step ids from prior waves (composite ids preferred).

    Returns:
        Copy of ``decision`` with validated dependencies and execution_mode.
    """
    if not decision.steps:
        return decision

    completed = set(completed_ids)
    in_plan_ids = {s.id for s in decision.steps}
    new_steps: list[StepAction] = []
    changed = False

    for step in decision.steps:
        raw_deps = list(step.dependencies or [])
        resolved: list[str] = []
        seen: set[str] = set()
        for dep in raw_deps:
            target = _resolve_dependency_ref(dep, completed_ids=completed, in_plan_ids=in_plan_ids)
            if target is None:
                if dep.strip():
                    logger.warning(
                        "Dropping unresolved plan dependency %r on step %r",
                        dep,
                        step.id,
                    )
                    changed = True
                continue
            if target not in seen:
                resolved.append(target)
                seen.add(target)
            if target != dep.strip():
                changed = True
        if resolved != raw_deps:
            changed = True
        new_steps.append(step.model_copy(update={"dependencies": resolved or None}))

    new_steps, inferred = _infer_linear_dependencies_when_mode_dependency(
        new_steps,
        execution_mode=decision.execution_mode,
    )
    if inferred:
        changed = True

    normalized_steps = _drop_in_plan_cycles(new_steps)
    if normalized_steps is not new_steps:
        changed = True

    has_deps = any(s.dependencies for s in normalized_steps)
    execution_mode = decision.execution_mode
    if has_deps and execution_mode != "dependency":
        execution_mode = "dependency"
        changed = True

    if not changed:
        return decision
    return decision.model_copy(update={"steps": normalized_steps, "execution_mode": execution_mode})
