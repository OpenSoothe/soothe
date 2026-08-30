"""Bounded CE DAG ops from report-commit judgment.

Allowed: wire/unwire depends_on, set priority, update pending briefs.
spawn/cancel require an explicit allowlist (empty by default — LoopRail owns
structural fan-out).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from soothe.context.engine import ContextEngine

logger = logging.getLogger(__name__)

DagOpKind = Literal[
    "wire_depends",
    "unwire_depends",
    "set_priority",
    "update_pending_brief",
    "spawn_goal",
    "cancel_goal",
]

# Structural spawn/cancel are denied unless listed (default: none).
_DEFAULT_STRUCTURAL_ALLOWLIST: frozenset[str] = frozenset()


class DagOp(BaseModel):
    """One bounded DAG mutation proposed by the report-commit judge."""

    op: DagOpKind = Field(description="Bounded op kind")
    goal_id: str = Field(
        default="",
        description="Target goal id (required for most ops)",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Dependency goal ids for wire/unwire",
    )
    priority: int | None = Field(
        default=None,
        description="New priority 0-100 for set_priority",
    )
    brief: str | None = Field(
        default=None,
        description="Replacement description for update_pending_brief",
    )


def format_dag_slice_for_judge(goals: list[Any], *, limit: int = 24) -> str:
    """Compact CE DAG slice text for the judge prompt."""
    if not goals:
        return ""
    lines: list[str] = []
    for g in goals[:limit]:
        gid = str(getattr(g, "id", "") or "")[:8]
        status = str(getattr(g, "status", "") or "")
        role = str(getattr(g, "role", "") or "")
        pri = getattr(g, "priority", "")
        deps = ",".join(str(d)[:8] for d in (getattr(g, "depends_on", None) or [])[:6])
        desc = str(getattr(g, "description", "") or "").replace("\n", " ")[:80]
        lines.append(f"- {gid} status={status} role={role} pri={pri} deps=[{deps}] {desc}")
    return "Pending/related CE goals:\n" + "\n".join(lines)


async def apply_bounded_dag_ops(
    ce: ContextEngine,
    ops: list[DagOp] | list[Any],
    *,
    source_goal_id: str,
    structural_allowlist: frozenset[str] | None = None,
) -> list[str]:
    """Validate and apply bounded DAG ops. Returns human-readable apply notes."""
    allow = (
        structural_allowlist if structural_allowlist is not None else _DEFAULT_STRUCTURAL_ALLOWLIST
    )
    notes: list[str] = []
    for raw in ops:
        op = raw if isinstance(raw, DagOp) else DagOp.model_validate(raw)
        try:
            note = await _apply_one(ce, op, source_goal_id=source_goal_id, allow=allow)
            if note:
                notes.append(note)
        except Exception:
            logger.warning(
                "Rejected/failed dag_op %s for source=%s",
                op.op,
                source_goal_id,
                exc_info=True,
            )
            notes.append(f"rejected:{op.op}")
    return notes


async def _apply_one(
    ce: ContextEngine,
    op: DagOp,
    *,
    source_goal_id: str,
    allow: frozenset[str],
) -> str:
    kind = op.op
    if kind in ("spawn_goal", "cancel_goal") and kind not in allow:
        logger.info(
            "Skipping structural dag_op %s (not allowlisted) source=%s",
            kind,
            source_goal_id,
        )
        return f"skipped:{kind}:not_allowlisted"

    target_id = (op.goal_id or "").strip()
    if kind in ("wire_depends", "unwire_depends", "set_priority", "update_pending_brief"):
        if not target_id:
            return f"rejected:{kind}:missing_goal_id"
        goal = await ce.get_goal(target_id)
        if goal is None:
            return f"rejected:{kind}:unknown_goal"

    if kind == "wire_depends":
        goal = await ce.get_goal(target_id)
        assert goal is not None
        added: list[str] = []
        for dep in op.depends_on:
            dep = str(dep).strip()
            if not dep or dep == target_id:
                continue
            if await ce.get_goal(dep) is None:
                continue
            if dep not in goal.depends_on:
                goal.depends_on.append(dep)
                added.append(dep)
        if added:
            goal.updated_at = datetime.now(UTC)
            return f"wired:{target_id}:+{','.join(added)}"
        return f"noop:wire:{target_id}"

    if kind == "unwire_depends":
        goal = await ce.get_goal(target_id)
        assert goal is not None
        remove = {str(d).strip() for d in op.depends_on if str(d).strip()}
        if not remove:
            return f"noop:unwire:{target_id}"
        before = list(goal.depends_on)
        goal.depends_on = [d for d in goal.depends_on if d not in remove]
        if goal.depends_on != before:
            goal.updated_at = datetime.now(UTC)
            return f"unwired:{target_id}:-{','.join(sorted(remove))}"
        return f"noop:unwire:{target_id}"

    if kind == "set_priority":
        goal = await ce.get_goal(target_id)
        assert goal is not None
        if op.priority is None:
            return "rejected:set_priority:missing_priority"
        new_pri = max(0, min(100, int(op.priority)))
        old = goal.priority
        goal.priority = new_pri
        goal.updated_at = datetime.now(UTC)
        return f"priority:{target_id}:{old}->{new_pri}"

    if kind == "update_pending_brief":
        goal = await ce.get_goal(target_id)
        assert goal is not None
        if goal.status != "pending":
            return "rejected:update_pending_brief:not_pending"
        brief = (op.brief or "").strip()
        if not brief:
            return "rejected:update_pending_brief:empty_brief"
        goal.description = brief
        goal.updated_at = datetime.now(UTC)
        return f"brief:{target_id}:updated"

    if kind == "cancel_goal":
        if not target_id:
            return "rejected:cancel_goal:missing_goal_id"
        await ce.cancel_goal(target_id, reason=f"judge_dag_op from {source_goal_id}")
        return f"cancelled:{target_id}"

    if kind == "spawn_goal":
        # Allowlisted only — still not free-form topology. Brief required.
        brief = (op.brief or "").strip()
        if not brief:
            return "rejected:spawn_goal:empty_brief"
        parent = await ce.get_goal(source_goal_id)
        parent_id = (parent.parent_id or source_goal_id) if parent is not None else source_goal_id
        created = await ce.create_goal(
            description=brief,
            priority=max(0, min(100, int(op.priority))) if op.priority is not None else 50,
            parent_id=parent_id,
            depends_on=list(op.depends_on or []),
            workspace=parent.workspace if parent else None,
        )
        return f"spawned:{created.id}"

    return f"rejected:unknown_op:{kind}"
