"""CE-facing LoopRail builtins (v1 test/runtime implementation).

Mutates ContextEngine goal DAG. Goal tags / branch metadata live in
``RailJobState`` until GoalNode gains first-class rail fields.

IG-687 adds greenfield-system builtins: plan_milestones, spawn_wave_makers
(with optional git worktrees), spawn_integrate, commit_milestone,
spawn_feedback_cycle (find → optimize → verify).
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from soothe.context.engine import ContextEngine
from soothe.context.models import TERMINAL_STATES, GoalNode

logger = logging.getLogger(__name__)

# Default parallel maker modules when greenfield has no custom plan.
_DEFAULT_WAVE_MODULES: tuple[str, ...] = ("core", "api", "cli", "tests")


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
    # greenfield-system wave state
    wave_index: int = 0
    max_waves: int = 3
    wave_modules: list[str] | None = None
    worktrees_enabled: bool = True
    # find→optimize→verify feedback rounds (greenfield)
    feedback_round: int = 0
    max_feedback_rounds: int = 8
    acceptance_met: bool = False


@dataclass
class BuiltinResult:
    """Outcome of invoking a CE rail builtin."""

    status: str  # success | error | skipped
    detail: str = ""
    created_goal_ids: list[str] = field(default_factory=list)


def _job_workspace(ce: ContextEngine, job_id: str) -> Path | None:
    root = ce._dag.get_goal(job_id)
    if root is None or not root.workspace:
        return None
    return Path(root.workspace).expanduser().resolve()


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists() or (path / ".git").is_file()


def _ensure_worktree(
    repo: Path,
    *,
    branch: str,
    worktree_path: Path,
) -> Path | None:
    """Create ``branch`` checked out at ``worktree_path``. Return path or None."""
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    if worktree_path.exists():
        return worktree_path
    try:
        # Prefer new branch from HEAD; fall back if branch already exists.
        proc = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path)],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            proc = subprocess.run(
                ["git", "worktree", "add", str(worktree_path), branch],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
        if proc.returncode != 0:
            logger.warning(
                "git worktree add failed for %s: %s",
                worktree_path,
                (proc.stderr or proc.stdout or "").strip()[:300],
            )
            return None
        return worktree_path
    except OSError as exc:
        logger.warning("git worktree unavailable: %s", exc)
        return None


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

    async def _do_plan_milestones(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        """Spawn architecture/milestone map; wire root to wait on it (not act as maker)."""
        del trigger_goal_id
        state = await self._require(job_id)
        ws = _job_workspace(self._ce, job_id)
        arch = await self._ce.create_goal(
            (
                f"Architecture and milestone map for job {job_id}. "
                "Define module boundaries, wave acceptance criteria, and "
                "git commit milestones. Do not implement product code here; "
                "produce a checkable milestone plan only."
            ),
            parent_id=job_id,
            source="decomposition",
            priority=80,
            workspace=str(ws) if ws else None,
            rail_id=state.rail_id,
        )
        await self.annotate_goal(
            arch.id,
            job_id,
            tags=["architecture", "planning", "milestones"],
            role="planner",
            branch_id=job_id,
        )
        root = await self._ce.get_goal(job_id)
        if root is not None:
            deps = list(root.depends_on or [])
            if arch.id not in deps:
                deps.append(arch.id)
            await self._ce.update_dependencies(job_id, deps)
        return BuiltinResult(
            status="success",
            detail="spawned architecture milestones",
            created_goal_ids=[arch.id],
        )

    async def _do_spawn_wave_makers(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        """Spawn parallel makers for the next wave; optional git worktrees."""
        state = await self._require(job_id)
        if state.wave_index >= state.max_waves:
            return BuiltinResult(
                status="skipped",
                detail=f"max_waves={state.max_waves} reached",
            )

        arch_ids = [
            gid
            for gid, ann in state.annotations.items()
            if "architecture" in ann.tags
            and (g := self._ce._dag.get_goal(gid)) is not None
            and g.status == "completed"
        ]
        depends = list(arch_ids)
        if trigger_goal_id and trigger_goal_id not in depends:
            # Next-wave trigger is usually QA; do not depend on root.
            tg = self._ce._dag.get_goal(trigger_goal_id)
            if tg is not None and tg.id != job_id:
                depends.append(trigger_goal_id)

        modules = list(state.wave_modules or _DEFAULT_WAVE_MODULES)
        if state.decompose_plan:
            modules = [
                str(spec.get("module") or spec.get("description") or f"m{i}")
                for i, spec in enumerate(state.decompose_plan)
            ]

        state.wave_index += 1
        wave = state.wave_index
        repo = _job_workspace(self._ce, job_id)
        created: list[str] = []

        for module in modules:
            slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in module)[:48]
            slug = slug.strip("-") or f"mod-{len(created) + 1}"
            maker_ws: str | None = str(repo) if repo else None
            branch = f"job/{job_id[:8]}/w{wave}/{slug}"
            if state.worktrees_enabled and repo is not None and _is_git_repo(repo):
                wt = repo / ".soothe" / "worktrees" / f"w{wave}-{slug}"
                ensured = _ensure_worktree(repo, branch=branch, worktree_path=wt)
                if ensured is not None:
                    maker_ws = str(ensured)

            desc = (
                f"Wave {wave} maker [{slug}] for job {job_id}. "
                f"Implement only the '{slug}' module ownership. "
                f"Work in workspace isolation (branch {branch}). "
                "Do not modify unrelated modules. Leave atomic commits on this "
                "branch for later integrate/commit gates."
            )
            goal = await self._ce.create_goal(
                desc,
                parent_id=job_id,
                depends_on=depends or None,
                source="decomposition",
                priority=75,
                workspace=maker_ws,
                rail_id=state.rail_id,
            )
            await self.annotate_goal(
                goal.id,
                job_id,
                tags=["implementation", "maker", f"wave-{wave}", slug],
                role="maker",
                branch_id=branch,
            )
            created.append(goal.id)

        # Root waits on makers (coordinator), makers never wait on root.
        root = await self._ce.get_goal(job_id)
        if root is not None and created:
            deps = list(root.depends_on or [])
            for gid in created:
                if gid not in deps:
                    deps.append(gid)
            await self._ce.update_dependencies(job_id, deps)

        return BuiltinResult(
            status="success",
            detail=f"spawned wave {wave} makers={len(created)}",
            created_goal_ids=created,
        )

    async def _do_spawn_integrate(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        """Spawn integrate/merge goal depending on completed wave makers."""
        state = await self._require(job_id)
        wave = state.wave_index
        makers = [
            gid
            for gid, ann in state.annotations.items()
            if "implementation" in ann.tags
            and f"wave-{wave}" in ann.tags
            and (g := self._ce._dag.get_goal(gid)) is not None
            and g.status == "completed"
        ]
        if not makers and trigger_goal_id:
            makers = [trigger_goal_id]
        ws = _job_workspace(self._ce, job_id)
        goal = await self._ce.create_goal(
            (
                f"Integrate wave {wave} for job {job_id}. "
                "Merge maker worktree branches into the job branch, resolve "
                "conflicts, and leave a clean tree ready for a milestone commit. "
                "Do not start unrelated features."
            ),
            parent_id=job_id,
            depends_on=makers or None,
            source="decomposition",
            priority=78,
            workspace=str(ws) if ws else None,
            rail_id=state.rail_id,
        )
        await self.annotate_goal(
            goal.id,
            job_id,
            tags=["integrate", f"wave-{wave}"],
            role="integrator",
            branch_id=job_id,
        )
        return BuiltinResult(
            status="success",
            detail=f"spawned integrate wave {wave}",
            created_goal_ids=[goal.id],
        )

    async def _do_commit_milestone(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        """Spawn git commit gate goal (diff-scoped evidence for review/QA)."""
        state = await self._require(job_id)
        wave = state.wave_index
        deps = [trigger_goal_id] if trigger_goal_id else []
        # Prefer integrate as dependency when present.
        integrates = [
            gid
            for gid, ann in state.annotations.items()
            if "integrate" in ann.tags
            and f"wave-{wave}" in ann.tags
            and (g := self._ce._dag.get_goal(gid)) is not None
            and g.status == "completed"
        ]
        if integrates:
            deps = integrates
        ws = _job_workspace(self._ce, job_id)
        goal = await self._ce.create_goal(
            (
                f"Commit milestone for wave {wave} of job {job_id}. "
                "Create one or more atomic git commits on the job branch covering "
                "this wave's modules. Commit messages must name the wave and "
                "modules. Do not push unless asked. Leave `git log` / `git show` "
                "evidence for the following review goal."
            ),
            parent_id=job_id,
            depends_on=deps or None,
            source="decomposition",
            priority=79,
            workspace=str(ws) if ws else None,
            rail_id=state.rail_id,
        )
        await self.annotate_goal(
            goal.id,
            job_id,
            tags=["commit", "milestone", f"wave-{wave}"],
            role="committer",
            branch_id=job_id,
        )
        return BuiltinResult(
            status="success",
            detail=f"spawned commit milestone wave {wave}",
            created_goal_ids=[goal.id],
        )

    async def _do_review(self, *, job_id: str, trigger_goal_id: str | None) -> BuiltinResult:
        deps = [trigger_goal_id] if trigger_goal_id else []
        state = await self._require(job_id)
        # Prefer commit milestone as review base when available.
        commits = [
            gid
            for gid, ann in state.annotations.items()
            if "commit" in ann.tags
            and (g := self._ce._dag.get_goal(gid)) is not None
            and g.status == "completed"
        ]
        if commits:
            deps = commits[-1:]
        ws = _job_workspace(self._ce, job_id)
        goal = await self._ce.create_goal(
            (
                f"Diff-scoped code review for job {job_id}. "
                "Review the milestone commit range (not an unclean dirty tree). "
                "Record findings; block on design/security issues; do not "
                "re-implement features."
            ),
            parent_id=job_id,
            depends_on=deps or None,
            source="decomposition",
            priority=80,
            workspace=str(ws) if ws else None,
            rail_id=state.rail_id,
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

    async def _do_spawn_feedback_cycle(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        """Spawn find→optimize→verify goals until acceptance (greenfield feedback)."""
        state = await self._require(job_id)
        if state.feedback_round >= state.max_feedback_rounds:
            return BuiltinResult(
                status="skipped",
                detail=f"max_feedback_rounds={state.max_feedback_rounds} reached",
            )
        if state.acceptance_met:
            return BuiltinResult(status="skipped", detail="acceptance already met")

        # Skip if a prior feedback chain is still in flight.
        for gid, ann in state.annotations.items():
            if "feedback" not in ann.tags:
                continue
            g = self._ce._dag.get_goal(gid)
            if g is not None and g.status not in TERMINAL_STATES:
                return BuiltinResult(
                    status="skipped",
                    detail=f"feedback inflight: {gid}",
                )

        state.feedback_round += 1
        round_n = state.feedback_round
        ws = _job_workspace(self._ce, job_id)
        ws_str = str(ws) if ws else None
        base_deps = [trigger_goal_id] if trigger_goal_id else []

        diagnose = await self._ce.create_goal(
            (
                f"Feedback round {round_n} diagnose for job {job_id}. "
                "Find bugs, acceptance gaps, and regressions against the "
                "architecture milestone criteria. Produce a concrete defect "
                "list; do not implement fixes here."
            ),
            parent_id=job_id,
            depends_on=base_deps or None,
            source="decomposition",
            priority=82,
            workspace=ws_str,
            rail_id=state.rail_id,
        )
        await self.annotate_goal(
            diagnose.id,
            job_id,
            tags=["feedback", "diagnose", f"feedback-{round_n}"],
            role="diagnoser",
            branch_id=job_id,
        )

        optimize = await self._ce.create_goal(
            (
                f"Feedback round {round_n} optimize for job {job_id}. "
                "Fix and optimize against the diagnose findings. Prefer "
                "minimal targeted changes; do not expand scope beyond gaps."
            ),
            parent_id=job_id,
            depends_on=[diagnose.id],
            source="decomposition",
            priority=78,
            workspace=ws_str,
            rail_id=state.rail_id,
        )
        await self.annotate_goal(
            optimize.id,
            job_id,
            tags=["feedback", "optimize", "implementation", f"feedback-{round_n}"],
            role="maker",
            branch_id=job_id,
        )

        verify = await self._ce.create_goal(
            (
                f"Feedback round {round_n} verify for job {job_id}. "
                "Re-run acceptance checks / golden tests against diagnose "
                "findings. Report remaining gaps; do not re-implement."
            ),
            parent_id=job_id,
            depends_on=[optimize.id],
            source="decomposition",
            priority=85,
            workspace=ws_str,
            rail_id=state.rail_id,
        )
        await self.annotate_goal(
            verify.id,
            job_id,
            tags=["feedback", "verify", "qa", f"feedback-{round_n}"],
            role="qa",
            branch_id=job_id,
        )

        return BuiltinResult(
            status="success",
            detail=f"spawned feedback cycle round {round_n}",
            created_goal_ids=[diagnose.id, optimize.id, verify.id],
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
