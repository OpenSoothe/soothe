"""CE-facing LoopRail builtins (v1 test/runtime implementation).

Mutates ContextEngine goal DAG. Goal tags / branch metadata live in
``RailJobState`` until GoalNode gains first-class rail fields.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from soothe.context.engine import ContextEngine
from soothe.context.models import TERMINAL_STATES, GoalNode

logger = logging.getLogger(__name__)


@dataclass
class GoalAnnotation:
    """Rail-side metadata for a CE goal."""

    tags: list[str] = field(default_factory=list)
    branch_id: str | None = None
    branch_status: str = "active"  # active | pruned | suspended
    role: str | None = None


@dataclass
class RailJobState:
    """Job-scoped rail binding and annotations."""

    job_id: str
    rail_id: str
    rail_version: str
    annotations: dict[str, GoalAnnotation] = field(default_factory=dict)
    suspended: bool = False
    completed: bool = False
    # Test knobs / decompose plans
    scout_count: int = 2
    decompose_plan: list[dict[str, Any]] | None = None


@dataclass
class BuiltinResult:
    """Outcome of invoking a CE rail builtin."""

    status: str  # success | error | skipped
    detail: str = ""
    created_goal_ids: list[str] = field(default_factory=list)


class RailBuiltinExecutor:
    """Execute ``then:`` verbs against ContextEngine + RailJobState."""

    def __init__(self, ce: ContextEngine) -> None:
        self._ce = ce
        self._jobs: dict[str, RailJobState] = {}
        self._lock = asyncio.Lock()

    async def bind_job(self, state: RailJobState) -> None:
        """Register or replace job state for a root goal id."""
        async with self._lock:
            self._jobs[state.job_id] = state
            self._jobs[state.job_id].annotations.setdefault(
                state.job_id,
                GoalAnnotation(tags=["job_root"], branch_id=state.job_id, role="root"),
            )

    async def job_state(self, job_id: str) -> RailJobState | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def annotation(self, goal_id: str, job_id: str) -> GoalAnnotation:
        async with self._lock:
            state = self._jobs[job_id]
            return state.annotations.setdefault(goal_id, GoalAnnotation())

    async def annotate_goal(
        self,
        goal_id: str,
        job_id: str,
        *,
        tags: list[str] | None = None,
        role: str | None = None,
        branch_id: str | None = None,
        branch_status: str | None = None,
    ) -> GoalAnnotation:
        """Update rail annotations and mirror them onto the CE GoalNode."""
        state = await self._require(job_id)
        ann = await self.annotation(goal_id, job_id)
        if tags is not None:
            ann.tags = list(tags)
        if role is not None:
            ann.role = role
        if branch_id is not None:
            ann.branch_id = branch_id
        if branch_status is not None:
            ann.branch_status = branch_status
        self._sync_goal_fields(goal_id, ann, rail_id=state.rail_id)
        return ann

    def _sync_goal_fields(
        self,
        goal_id: str,
        ann: GoalAnnotation,
        *,
        rail_id: str | None = None,
    ) -> None:
        """Mirror rail annotations onto the CE GoalNode (IG-678 P2-2)."""
        goal = self._ce._dag.get_goal(goal_id)
        if goal is None:
            return
        if rail_id is not None:
            goal.rail_id = rail_id
        goal.rail_tags = list(ann.tags)
        goal.branch_id = ann.branch_id
        if ann.branch_status in ("active", "pruned", "suspended"):
            goal.branch_status = ann.branch_status  # type: ignore[assignment]
        goal.role = ann.role

    async def tags_by_goal(self, job_id: str) -> dict[str, list[str]]:
        async with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return {}
            return {gid: list(ann.tags) for gid, ann in state.annotations.items()}

    async def invoke(
        self,
        builtin: str,
        *,
        job_id: str,
        trigger_goal_id: str | None = None,
    ) -> BuiltinResult:
        """Dispatch a CE builtin by name."""
        handler = getattr(self, f"_do_{builtin}", None)
        if handler is None:
            return BuiltinResult(status="error", detail=f"unknown builtin: {builtin}")
        try:
            return await handler(job_id=job_id, trigger_goal_id=trigger_goal_id)
        except Exception as exc:
            logger.exception("Rail builtin %s failed", builtin)
            return BuiltinResult(
                status="error",
                detail=f"{type(exc).__name__}: builtin {builtin} failed",
            )

    async def _do_decompose_parallel(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        state = await self._require(job_id)
        plan = state.decompose_plan
        if plan is None:
            plan = [
                {
                    "description": f"Explore facet {i + 1} for job {job_id}",
                    "tags": ["exploration"],
                    "role": "scout",
                }
                for i in range(state.scout_count)
            ]
        created: list[str] = []
        for spec in plan:
            tags = list(spec.get("tags") or ["exploration"])
            goal = await self._ce.create_goal(
                str(spec["description"]),
                parent_id=job_id,
                source="decomposition",
                priority=int(spec.get("priority", 60)),
                rail_id=state.rail_id,
            )
            await self.annotate_goal(
                goal.id,
                job_id,
                tags=tags,
                branch_id=job_id,
                role=str(spec.get("role") or "scout"),
            )
            created.append(goal.id)
        return BuiltinResult(
            status="success",
            detail=f"spawned {len(created)} goals",
            created_goal_ids=created,
        )

    async def _do_plan_and_implement(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        state = await self._require(job_id)
        informs = [
            gid
            for gid, ann in state.annotations.items()
            if "exploration" in ann.tags
            and (g := self._ce._dag.get_goal(gid)) is not None
            and g.status == "completed"
        ]
        plan = await self._ce.create_goal(
            f"Plan implementation for job {job_id}",
            parent_id=job_id,
            depends_on=informs or None,
            source="decomposition",
            priority=70,
            informs=informs,
            rail_id=state.rail_id,
        )
        await self.annotate_goal(
            plan.id, job_id, tags=["planning"], role="planner", branch_id=job_id
        )

        impl = await self._ce.create_goal(
            f"Implement for job {job_id}",
            parent_id=job_id,
            depends_on=[plan.id],
            source="decomposition",
            priority=75,
            informs=informs,
            rail_id=state.rail_id,
        )
        await self.annotate_goal(
            impl.id, job_id, tags=["implementation"], role="maker", branch_id=job_id
        )
        return BuiltinResult(
            status="success",
            detail="spawned plan+implement",
            created_goal_ids=[plan.id, impl.id],
        )

    async def _do_review(self, *, job_id: str, trigger_goal_id: str | None) -> BuiltinResult:
        deps = [trigger_goal_id] if trigger_goal_id else []
        goal = await self._ce.create_goal(
            f"Review changes for job {job_id}",
            parent_id=job_id,
            depends_on=deps or None,
            source="decomposition",
            priority=80,
            rail_id=(await self._require(job_id)).rail_id,
        )
        await self.annotate_goal(goal.id, job_id, tags=["review"], role="checker", branch_id=job_id)
        return BuiltinResult(
            status="success",
            detail="spawned review",
            created_goal_ids=[goal.id],
        )

    async def _do_qa_verify(self, *, job_id: str, trigger_goal_id: str | None) -> BuiltinResult:
        deps = [trigger_goal_id] if trigger_goal_id else []
        goal = await self._ce.create_goal(
            f"QA verify for job {job_id}",
            parent_id=job_id,
            depends_on=deps or None,
            source="decomposition",
            priority=85,
            rail_id=(await self._require(job_id)).rail_id,
        )
        await self.annotate_goal(goal.id, job_id, tags=["qa"], role="qa", branch_id=job_id)
        return BuiltinResult(
            status="success",
            detail="spawned qa",
            created_goal_ids=[goal.id],
        )

    async def _do_retry_branch(self, *, job_id: str, trigger_goal_id: str | None) -> BuiltinResult:
        state = await self._require(job_id)
        # Prune non-terminal active/pending descendants on same branch; salvage completed.
        salvaged: list[str] = []
        pruned: list[str] = []
        for goal in list(await self._ce.list_goals()):
            if goal.id == job_id or goal.parent_id != job_id:
                continue
            if goal.status == "completed":
                salvaged.append(goal.id)
                await self.annotate_goal(goal.id, job_id, branch_status="pruned")
                continue
            if goal.status in TERMINAL_STATES:
                await self.annotate_goal(goal.id, job_id, branch_status="pruned")
                continue
            # Cancel in-flight / pending via CE state machine API (not direct mutation)
            await self._ce.cancel_goal(goal.id, reason="rail:retry_branch_prune")
            await self.annotate_goal(goal.id, job_id, branch_status="pruned")
            pruned.append(goal.id)

        replacement = await self._ce.create_goal(
            f"Replanted branch for job {job_id}",
            parent_id=job_id,
            source="decomposition",
            priority=70,
            informs=salvaged,
            rail_id=state.rail_id,
        )
        await self.annotate_goal(
            replacement.id,
            job_id,
            tags=["implementation", "replant"],
            role="maker",
            branch_id=replacement.id,
        )
        return BuiltinResult(
            status="success",
            detail=f"pruned={len(pruned)} salvaged={len(salvaged)}",
            created_goal_ids=[replacement.id],
        )

    async def _do_merge_branches(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        return BuiltinResult(status="success", detail="merge noop in v1 harness")

    async def _do_pause_for_user(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        state = await self._require(job_id)
        state.suspended = True
        if trigger_goal_id:
            await self.annotate_goal(trigger_goal_id, job_id, branch_status="suspended")
        root = await self._ce.get_goal(job_id)
        if root is not None and root.status not in TERMINAL_STATES:
            await self._ce.suspend_goal(job_id, reason="rail:pause_for_user")
        return BuiltinResult(status="success", detail="job suspended for user")

    async def _do_complete_job(self, *, job_id: str, trigger_goal_id: str | None) -> BuiltinResult:
        state = await self._require(job_id)
        root = await self._ce.get_goal(job_id)
        if root is None:
            return BuiltinResult(status="error", detail="job root missing")
        if root.status not in TERMINAL_STATES:
            await self._ce.complete_goal(job_id)
        state.completed = True
        state.suspended = False
        return BuiltinResult(status="success", detail="job completed")

    async def _require(self, job_id: str) -> RailJobState:
        async with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                msg = f"job {job_id} not bound to rail builtins"
                raise KeyError(msg)
            return state

    async def descendant_goals(self, job_id: str) -> list[GoalNode]:
        return [g for g in self._ce._dag.goals.values() if g.id == job_id or g.parent_id == job_id]
