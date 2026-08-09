"""CE-facing LoopRail builtins + Rail Exec dispatch (RFC-231).

Mutates ContextEngine goal DAG. Goal tags / branch metadata are mirrored onto
``GoalNode.rail_*`` and also kept in ``RailJobState`` for wave counters.
``tags_by_goal`` falls back to CE ``rail_tags``, hydrates annotations on bind,
and optionally persists ``rail_state.json`` under the job artifact dir so
guards survive daemon restart.

``invoke`` prefers YAML ``verbs.<name>.do`` recipes over ``_do_*``.
Wave fan-out applies a flat WavePlan into ``RailJobState`` (SoT) from
structured completion fields, recommended dumps, ``wave_plan_path``, or
findings JSON — then mirrors recommended dump paths best-effort.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from soothe.autopilot.rail import worktree_ops
from soothe.autopilot.rail.wave_plan import (
    WavePlan,
    apply_wave_plan_to_state_fields,
    build_wave_plan,
    diagnose_wave_plan_from_sources,
    dump_wave_plan,
    jobs_wave_plan_path,
    parse_wave_plan_payload,
    resolve_fanout_slices,
    workspace_wave_plan_path,
)
from soothe.context.engine import ContextEngine
from soothe.context.models import TERMINAL_STATES, GoalNode
from soothe.rails.verb_defaults import (
    DEFAULT_VERB_ROLES,
    DEFAULT_VERB_TAGS,
    resolve_verb_brief,
    resolve_verb_field,
    waveplan_verify_existing_brief,
)

logger = logging.getLogger(__name__)

_RAIL_STATE_FILENAME = "rail_state.json"


def _coerce_verb_overrides(raw: Any) -> dict[str, dict[str, Any]]:
    """Normalize persisted / bound verb override mapping."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, body in raw.items():
        if not isinstance(name, str) or not isinstance(body, dict):
            continue
        entry: dict[str, Any] = {}
        brief = body.get("brief")
        if isinstance(brief, str) and brief.strip():
            entry["brief"] = brief.strip()
        tags = body.get("tags")
        if isinstance(tags, list):
            entry["tags"] = [str(t).strip() for t in tags if str(t).strip()]
        role = body.get("role")
        if isinstance(role, str) and role.strip():
            entry["role"] = role.strip()
        do_steps = body.get("do")
        if isinstance(do_steps, list) and do_steps:
            entry["do"] = do_steps
        if entry:
            out[name.strip()] = entry
    return out


@dataclass
class GoalAnnotation:
    """Rail-side metadata for a CE goal."""

    tags: list[str] = field(default_factory=list)
    branch_id: str | None = None
    branch_status: str = "active"  # active | pruned | suspended | merged | conflict
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
    # Test knobs / decompose plans (None = unset; coalesce at use sites)
    scout_count: int | None = None
    decompose_plan: list[dict[str, Any]] | None = None
    # Fan-out catalog (streaming spawn; wave_index is legacy/trace only)
    wave_index: int = 0
    max_waves: int = 32  # legacy alias / default expansion budget; prefer max_slices
    max_slices: int | None = None
    wave_slices: list[str] | None = None
    spawned_slices: dict[str, str] = field(default_factory=dict)
    job_branch: str | None = None
    base_branch: str | None = None
    # Path that supplied the WavePlan when ingested from a file (optional).
    wave_plan_source_path: str | None = None
    worktrees_enabled: bool = True
    # True when bind declared rail YAML ``fanout:`` (structure signal for guards).
    fanout_enabled: bool = False
    # When True, makers require WavePlan applied into job state (multi-form ingest).
    require_plan: bool = False
    # Engine spawn budget mirrored at bind (None = unset until bind).
    engine_max_parallel_goals: int | None = None
    # find→optimize→verify feedback rounds (fan-out rails)
    feedback_round: int = 0
    max_feedback_rounds: int = 8
    acceptance_met: bool = False
    # RFC-231 M2: rail YAML ``verbs:`` overrides (brief/tags/role per catalog verb)
    verb_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    def effective_scout_count(self) -> int:
        """Scout fan-out width (default 2 when unset)."""
        return int(self.scout_count) if self.scout_count is not None else 2

    def effective_engine_max_parallel_goals(self) -> int:
        """Spawn clamp (default 32 when unset)."""
        return (
            int(self.engine_max_parallel_goals)
            if self.engine_max_parallel_goals is not None
            else 32
        )

    def effective_max_slices(self) -> int:
        """Catalog expansion budget (default max_waves / 32)."""
        if self.max_slices is not None:
            return int(self.max_slices)
        return int(self.max_waves) if self.max_waves else 32


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


class RailBuiltinExecutor:
    """Execute ``then:`` verbs against ContextEngine + RailJobState."""

    def __init__(
        self,
        ce: ContextEngine,
        *,
        jobs_root: Path | None = None,
    ) -> None:
        self._ce = ce
        self._jobs: dict[str, RailJobState] = {}
        self._lock = asyncio.Lock()
        self._jobs_root = jobs_root

    async def bind_job(self, state: RailJobState) -> None:
        """Register or replace job state for a root goal id.

        Merges prior in-memory state and on-disk ``rail_state.json``, then
        hydrates annotations from CE ``GoalNode.rail_*`` (IG-691).
        """
        async with self._lock:
            loaded = self._load_rail_state_unlocked(state.job_id)
            prev = self._jobs.get(state.job_id)
            merged = state
            if loaded is not None:
                merged = self._merge_rail_state(state, loaded)
            elif prev is not None:
                merged = self._merge_rail_state(state, prev)
            self._hydrate_annotations_from_ce(merged)
            merged.annotations.setdefault(
                merged.job_id,
                GoalAnnotation(
                    tags=["job_root"],
                    branch_id=merged.job_id,
                    role="root",
                ),
            )
            self._jobs[merged.job_id] = merged
            self._persist_rail_state_unlocked(merged)

    async def set_acceptance_met(self, job_id: str, *, met: bool) -> None:
        """Persist job acceptance latch for rail guards (RFC-230)."""
        async with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return
            state.acceptance_met = bool(met)
            self._persist_rail_state_unlocked(state)

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
        async with self._lock:
            self._persist_rail_state_unlocked(state)
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
        # CE GoalNode only accepts active|pruned|suspended; merged/conflict stay
        # on RailJobState annotations (IG-732).
        if ann.branch_status in ("active", "pruned", "suspended"):
            goal.branch_status = ann.branch_status  # type: ignore[assignment]
        goal.role = ann.role

    def _job_descendants(self, job_id: str) -> list[GoalNode]:
        return [g for g in self._ce._dag.goals.values() if g.id == job_id or g.parent_id == job_id]

    def _hydrate_annotations_from_ce(self, state: RailJobState) -> None:
        """Fill missing annotation fields from persisted CE GoalNode rail_*."""
        for goal in self._job_descendants(state.job_id):
            if not (goal.rail_tags or goal.role or goal.branch_id):
                continue
            ann = state.annotations.setdefault(goal.id, GoalAnnotation())
            if goal.rail_tags:
                if not ann.tags:
                    ann.tags = list(goal.rail_tags)
                else:
                    for tag in goal.rail_tags:
                        if tag not in ann.tags:
                            ann.tags.append(tag)
            if goal.role and not ann.role:
                ann.role = goal.role
            if goal.branch_id and not ann.branch_id:
                ann.branch_id = goal.branch_id
            if goal.branch_status in ("active", "pruned", "suspended") and ann.branch_status in {
                "active",
                "",
            }:
                ann.branch_status = goal.branch_status

    @staticmethod
    def _merge_rail_state(base: RailJobState, donor: RailJobState) -> RailJobState:
        """Prefer ``base`` identity; keep donor annotations / catalog maps."""
        annotations = dict(donor.annotations)
        annotations.update(base.annotations)
        spawned = dict(donor.spawned_slices or {})
        spawned.update(base.spawned_slices or {})
        return RailJobState(
            job_id=base.job_id,
            rail_id=base.rail_id or donor.rail_id,
            rail_version=base.rail_version or donor.rail_version,
            annotations=annotations,
            suspended=base.suspended or donor.suspended,
            completed=base.completed or donor.completed,
            scout_count=base.scout_count if base.scout_count is not None else donor.scout_count,
            decompose_plan=base.decompose_plan
            if base.decompose_plan is not None
            else donor.decompose_plan,
            wave_index=max(base.wave_index, donor.wave_index),
            max_waves=max(base.max_waves, donor.max_waves),
            max_slices=base.max_slices if base.max_slices is not None else donor.max_slices,
            wave_slices=base.wave_slices if base.wave_slices is not None else donor.wave_slices,
            spawned_slices=spawned,
            job_branch=base.job_branch or donor.job_branch,
            base_branch=base.base_branch or donor.base_branch,
            wave_plan_source_path=base.wave_plan_source_path
            if base.wave_plan_source_path is not None
            else donor.wave_plan_source_path,
            worktrees_enabled=donor.worktrees_enabled,
            fanout_enabled=base.fanout_enabled or donor.fanout_enabled,
            require_plan=base.require_plan or donor.require_plan,
            engine_max_parallel_goals=base.engine_max_parallel_goals
            if base.engine_max_parallel_goals is not None
            else donor.engine_max_parallel_goals,
            feedback_round=max(base.feedback_round, donor.feedback_round),
            max_feedback_rounds=max(base.max_feedback_rounds, donor.max_feedback_rounds),
            acceptance_met=base.acceptance_met or donor.acceptance_met,
            verb_overrides=base.verb_overrides
            if base.verb_overrides
            else dict(donor.verb_overrides or {}),
        )

    async def _persist_job(self, state: RailJobState) -> None:
        async with self._lock:
            self._persist_rail_state_unlocked(state)

    def _rail_state_path(self, job_id: str) -> Path | None:
        if self._jobs_root is None:
            return None
        safe = job_id.replace("/", "_").replace("\\", "_")
        if ".." in safe or not safe.strip():
            return None
        return self._jobs_root / safe / _RAIL_STATE_FILENAME

    def _persist_rail_state_unlocked(self, state: RailJobState) -> None:
        path = self._rail_state_path(state.job_id)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "job_id": state.job_id,
                "rail_id": state.rail_id,
                "rail_version": state.rail_version,
                "suspended": state.suspended,
                "completed": state.completed,
                "scout_count": state.scout_count,
                "decompose_plan": state.decompose_plan,
                "wave_index": state.wave_index,
                "max_waves": state.max_waves,
                "max_slices": state.max_slices,
                "wave_slices": state.wave_slices,
                "spawned_slices": state.spawned_slices,
                "job_branch": state.job_branch,
                "base_branch": state.base_branch,
                "wave_plan_source_path": state.wave_plan_source_path,
                "worktrees_enabled": state.worktrees_enabled,
                "fanout_enabled": state.fanout_enabled,
                "require_plan": state.require_plan,
                "engine_max_parallel_goals": state.engine_max_parallel_goals,
                "feedback_round": state.feedback_round,
                "max_feedback_rounds": state.max_feedback_rounds,
                "acceptance_met": state.acceptance_met,
                "verb_overrides": state.verb_overrides,
                "annotations": {gid: asdict(ann) for gid, ann in state.annotations.items()},
            }
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except OSError:
            logger.debug("Failed to persist rail state for %s", state.job_id, exc_info=True)

    def _load_rail_state_unlocked(self, job_id: str) -> RailJobState | None:
        path = self._rail_state_path(job_id)
        if path is None or not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.debug("Failed to load rail state for %s", job_id, exc_info=True)
            return None
        if not isinstance(raw, dict):
            return None
        annotations: dict[str, GoalAnnotation] = {}
        for gid, ann_raw in (raw.get("annotations") or {}).items():
            if not isinstance(ann_raw, dict):
                continue
            annotations[str(gid)] = GoalAnnotation(
                tags=list(ann_raw.get("tags") or []),
                branch_id=ann_raw.get("branch_id"),
                branch_status=str(ann_raw.get("branch_status") or "active"),
                role=ann_raw.get("role"),
            )
        spawned_raw = raw.get("spawned_slices") or {}
        spawned: dict[str, str] = {}
        if isinstance(spawned_raw, dict):
            for k, v in spawned_raw.items():
                if k and v:
                    spawned[str(k)] = str(v)
        max_slices = int(raw["max_slices"]) if raw.get("max_slices") is not None else None
        return RailJobState(
            job_id=str(raw.get("job_id") or job_id),
            rail_id=str(raw.get("rail_id") or ""),
            rail_version=str(raw.get("rail_version") or ""),
            annotations=annotations,
            suspended=bool(raw.get("suspended")),
            completed=bool(raw.get("completed")),
            scout_count=int(raw["scout_count"]) if raw.get("scout_count") is not None else None,
            decompose_plan=raw.get("decompose_plan"),
            wave_index=int(raw.get("wave_index") or 0),
            max_waves=int(raw.get("max_waves") or 32),
            max_slices=max_slices,
            wave_slices=raw.get("wave_slices"),
            spawned_slices=spawned,
            job_branch=str(raw["job_branch"]) if raw.get("job_branch") else None,
            base_branch=str(raw["base_branch"]) if raw.get("base_branch") else None,
            wave_plan_source_path=(
                str(raw["wave_plan_source_path"]) if raw.get("wave_plan_source_path") else None
            ),
            worktrees_enabled=bool(raw.get("worktrees_enabled", True)),
            fanout_enabled=bool(raw.get("fanout_enabled", raw.get("require_plan", False))),
            require_plan=bool(raw.get("require_plan", False)),
            engine_max_parallel_goals=(
                int(raw["engine_max_parallel_goals"])
                if raw.get("engine_max_parallel_goals") is not None
                else None
            ),
            feedback_round=int(raw.get("feedback_round") or 0),
            max_feedback_rounds=int(raw.get("max_feedback_rounds") or 8),
            acceptance_met=bool(raw.get("acceptance_met")),
            verb_overrides=_coerce_verb_overrides(raw.get("verb_overrides")),
        )

    def _tags_by_goal_unlocked(self, job_id: str) -> dict[str, list[str]]:
        """Union in-memory annotations with CE ``rail_tags`` (IG-691)."""
        out: dict[str, list[str]] = {}
        state = self._jobs.get(job_id)
        if state is not None:
            for gid, ann in state.annotations.items():
                if ann.tags:
                    out[gid] = list(ann.tags)
        for goal in self._job_descendants(job_id):
            ce_tags = list(goal.rail_tags or [])
            if not ce_tags:
                continue
            existing = out.get(goal.id, [])
            if not existing:
                out[goal.id] = ce_tags
                continue
            merged = list(existing)
            for tag in ce_tags:
                if tag not in merged:
                    merged.append(tag)
            out[goal.id] = merged
        return out

    async def tags_by_goal(self, job_id: str) -> dict[str, list[str]]:
        async with self._lock:
            return self._tags_by_goal_unlocked(job_id)

    async def ensure_trigger_tags(self, job_id: str, goal_id: str) -> list[str]:
        """Fail-closed repair: hydrate annotation tags from CE ``rail_tags`` (IG-692).

        When in-memory annotations lack tags after restart, copy CE tags into
        the annotation map and return the resolved tag list.
        """
        async with self._lock:
            state = self._jobs.get(job_id)
            tags = self._tags_by_goal_unlocked(job_id).get(goal_id, [])
            if tags:
                return list(tags)
            goal = self._ce._dag.get_goal(goal_id)
            ce_tags = list(goal.rail_tags or []) if goal is not None else []
            if not ce_tags:
                return []
            if state is not None:
                ann = state.annotations.setdefault(goal_id, GoalAnnotation())
                if not ann.tags:
                    ann.tags = list(ce_tags)
                    if goal is not None and goal.role and not ann.role:
                        ann.role = goal.role
                    self._persist_rail_state_unlocked(state)
            return list(ce_tags)

    def _acceptance_brief_for_job(self, job_id: str) -> str:
        """Acceptance contract blurb for QA/verify goal descriptions."""
        from soothe.autopilot.verify.job_maturity import acceptance_contract_brief

        root = self._ce._dag.get_goal(job_id)
        ws = _job_workspace(self._ce, job_id)
        return acceptance_contract_brief(
            verification_rules=root.verification_rules if root else None,
            workspace=str(ws) if ws else (root.workspace if root else None),
            jobs_root=self._jobs_root,
            job_id=job_id,
            maturity=root.maturity if root else None,
        )

    async def invoke(
        self,
        builtin: str,
        *,
        job_id: str,
        trigger_goal_id: str | None = None,
    ) -> BuiltinResult:
        """Dispatch a catalog verb: prefer YAML ``do:`` recipe, else ``_do_*``."""
        try:
            if builtin == "plan_milestones":
                await self.ingest_wave_plan(job_id)
                if self._has_wave_plan_reuse_candidate(job_id):
                    return await self._plan_milestones_verify_existing(job_id=job_id)
            state = await self.job_state(job_id)
            steps = None
            if state is not None:
                body = (state.verb_overrides or {}).get(builtin) or {}
                raw_do = body.get("do")
                if isinstance(raw_do, list) and raw_do:
                    steps = raw_do
            if steps is not None:
                from soothe.autopilot.rail.recipe_exec import RecipeRunner

                return await RecipeRunner(self).run(
                    steps, job_id=job_id, trigger_goal_id=trigger_goal_id
                )
            handler = getattr(self, f"_do_{builtin}", None)
            if handler is None:
                return BuiltinResult(status="error", detail=f"unknown builtin: {builtin}")
            return await handler(job_id=job_id, trigger_goal_id=trigger_goal_id)
        except Exception as exc:
            logger.exception("Rail builtin %s failed", builtin)
            return BuiltinResult(
                status="error",
                detail=f"{type(exc).__name__}: builtin {builtin} failed",
            )

    def _has_architecture_annotation(self, job_id: str) -> bool:
        """True when any architecture/planner annotation exists (incl. pruned)."""
        state = self._jobs.get(job_id)
        if state is None:
            return False
        for ann in state.annotations.values():
            tags = list(ann.tags or [])
            if "architecture" in tags or (ann.role or "") == "planner":
                return True
        return False

    def _has_wave_plan_reuse_candidate(self, job_id: str) -> bool:
        """Whether plan_milestones should spawn a verify planner for a dump.

        Requires transfer evidence (recorded source path or diagnosable dump),
        not a bare ``wave_slices`` seed. Never short-path after a prior
        architecture attempt (retry must spawn a normal planner).
        """
        state = self._jobs.get(job_id)
        if state is None:
            return False
        if self._has_architecture_annotation(job_id):
            return False
        if not self.is_wave_plan_ready(job_id):
            return False
        if state.wave_plan_source_path:
            return True
        diagnosed = self._diagnose_job_wave_plan(state)
        return diagnosed.plan is not None and bool(diagnosed.source_path)

    async def _plan_milestones_verify_existing(self, *, job_id: str) -> BuiltinResult:
        """Spawn a pending trivial StrangeLoop planner to verify a candidate dump.

        Host never auto-completes architecture or spawns makers here — the
        agent must accept (wave_plan_path / inline wave_plan) or rewrite.
        """
        await self.ingest_wave_plan(job_id)
        state = await self._require(job_id)

        diagnosed = self._diagnose_job_wave_plan(state)
        source = state.wave_plan_source_path or diagnosed.source_path or "rail_state"
        if not source or source == "rail_state":
            return BuiltinResult(
                status="error",
                detail="WavePlan verify requested but no dump source path",
            )

        brief = waveplan_verify_existing_brief(job_id=job_id, source=str(source))
        tags = list(DEFAULT_VERB_TAGS["plan_milestones"])
        role = DEFAULT_VERB_ROLES["plan_milestones"]
        ws = _job_workspace(self._ce, job_id)
        arch = await self._ce.create_goal(
            brief,
            parent_id=job_id,
            source="decomposition",
            priority=80,
            workspace=str(ws) if ws else None,
            rail_id=state.rail_id,
            intake_scope="trivial",
        )
        await self.annotate_goal(
            arch.id,
            job_id,
            tags=tags,
            role=role,
            branch_id=job_id,
        )
        root = await self._ce.get_goal(job_id)
        if root is not None:
            deps = list(root.depends_on or [])
            if arch.id not in deps:
                deps.append(arch.id)
            await self._ce.update_dependencies(job_id, deps)

        logger.info(
            "plan_milestones verify existing WavePlan job=%s arch=%s source=%s "
            "intake_scope=trivial",
            job_id[:8],
            arch.id[:8],
            source,
        )
        return BuiltinResult(
            status="success",
            detail=f"verify existing WavePlan (source={source})",
            created_goal_ids=[arch.id],
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
                for i in range(state.effective_scout_count())
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
        planner_brief = resolve_verb_brief(
            "plan_milestones",
            job_id=job_id,
            overrides=state.verb_overrides,
        )
        if not planner_brief:
            return BuiltinResult(
                status="error",
                detail="plan_milestones brief missing (no default and no verbs override)",
            )
        tags = resolve_verb_field(
            "plan_milestones",
            "tags",
            overrides=state.verb_overrides,
            defaults=DEFAULT_VERB_TAGS,
        )
        if not isinstance(tags, list) or not tags:
            tags = list(DEFAULT_VERB_TAGS["plan_milestones"])
        role = resolve_verb_field(
            "plan_milestones",
            "role",
            overrides=state.verb_overrides,
            defaults=DEFAULT_VERB_ROLES,
        )
        if not isinstance(role, str) or not role:
            role = DEFAULT_VERB_ROLES["plan_milestones"]
        arch = await self._ce.create_goal(
            planner_brief,
            parent_id=job_id,
            source="decomposition",
            priority=80,
            workspace=str(ws) if ws else None,
            rail_id=state.rail_id,
        )
        await self.annotate_goal(
            arch.id,
            job_id,
            tags=[str(t) for t in tags],
            role=role,
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

    async def record_wave_plan(
        self,
        job_id: str,
        plan: WavePlan | dict[str, Any] | None = None,
        *,
        wave_slices: list[str] | None = None,
        slices: list[dict[str, Any]] | None = None,
        rationale: str | None = None,
        independence: str | None = None,
        max_waves: int | None = None,
        scout_count: int | None = None,
        source_path: str | None = None,
    ) -> WavePlan | None:
        """Apply a flat WavePlan into rail state (job-state SoT).

        Host API for Autopilot/rail. Mirrors recommended dump paths best-effort.
        Not a nano agent tool.
        """
        async with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return None
            if plan is None:
                built = build_wave_plan(
                    wave_slices=wave_slices,
                    slices=slices,
                    rationale=rationale,
                    independence=independence,
                    max_waves=max_waves,
                    scout_count=scout_count,
                )
            elif isinstance(plan, WavePlan):
                built = plan
            else:
                parsed = parse_wave_plan_payload(plan, source="record_wave_plan")
                if parsed is None:
                    return None
                built = parsed
            if not built.resolved_slice_ids() and built.scout_count is None:
                return None
            self._apply_wave_plan_unlocked(state, built, source_path=source_path)
            self._mirror_wave_plan_dumps_unlocked(state, built)
            self._persist_rail_state_unlocked(state)
            return built

    async def ingest_wave_plan(self, job_id: str) -> RailJobState | None:
        """Load WavePlan from multi-form sources into job state when unset."""
        async with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return None
            self._ingest_job_wave_plan(state)
            self._persist_rail_state_unlocked(state)
            return state

    def is_wave_plan_ready(self, job_id: str) -> bool:
        """Whether a usable WavePlan is available for spawn guards."""
        state = self._jobs.get(job_id)
        if state is None:
            return False
        if state.wave_slices:
            return True
        return self._diagnose_job_wave_plan(state).plan is not None

    def _apply_wave_plan_unlocked(
        self,
        state: RailJobState,
        plan: WavePlan,
        *,
        source_path: str | None = None,
    ) -> None:
        updates = apply_wave_plan_to_state_fields(plan)
        names = updates.get("wave_slices")
        if names:
            state.wave_slices = list(names)
        if updates.get("decompose_plan") is not None:
            state.decompose_plan = updates["decompose_plan"]
        if updates.get("scout_count") is not None:
            state.scout_count = int(updates["scout_count"])
        if updates.get("max_slices") is not None:
            state.max_slices = int(updates["max_slices"])
            state.max_waves = max(state.max_waves, int(updates["max_slices"]))
        elif updates.get("max_waves") is not None:
            state.max_waves = max(state.wave_index, int(updates["max_waves"]))
            state.max_slices = int(updates["max_waves"])
        if source_path:
            state.wave_plan_source_path = source_path
        logger.info(
            "Applied wave plan for job %s slices=%s scout_count=%s max_slices=%s source=%s",
            state.job_id[:8],
            state.wave_slices,
            state.scout_count,
            state.effective_max_slices(),
            state.wave_plan_source_path,
        )

    def _mirror_wave_plan_dumps_unlocked(self, state: RailJobState, plan: WavePlan) -> None:
        """Best-effort write recommended dump paths after successful apply."""
        if self._jobs_root is not None:
            job_path = jobs_wave_plan_path(self._jobs_root, state.job_id)
            if job_path is not None:
                try:
                    dump_wave_plan(job_path, plan)
                except OSError:
                    logger.debug(
                        "Failed to mirror jobs wave-plan dump for %s",
                        state.job_id[:8],
                        exc_info=True,
                    )
        ws = _job_workspace(self._ce, state.job_id)
        if ws is not None:
            try:
                dump_wave_plan(workspace_wave_plan_path(ws), plan)
            except OSError:
                logger.debug(
                    "Failed to mirror workspace wave-plan dump for %s",
                    state.job_id[:8],
                    exc_info=True,
                )

    def _diagnose_job_wave_plan(
        self,
        state: RailJobState,
        *,
        wave_plan: dict[str, Any] | WavePlan | None = None,
        wave_plan_path: str | None = None,
        findings: list[Any] | None = None,
    ):
        """Multi-source diagnose for a bound job."""
        ws = _job_workspace(self._ce, state.job_id)
        finding_candidates: list[Any] = list(findings or [])
        if not finding_candidates:
            for gid, ann in state.annotations.items():
                if "architecture" not in ann.tags:
                    continue
                goal = self._ce._dag.get_goal(gid)
                if goal is None:
                    continue
                finding_candidates.extend(list(goal.findings or []))
        return diagnose_wave_plan_from_sources(
            wave_plan=wave_plan,
            wave_plan_path=wave_plan_path,
            workspace=ws,
            jobs_root=self._jobs_root,
            job_id=state.job_id,
            findings=finding_candidates or None,
        )

    def _ingest_job_wave_plan(self, state: RailJobState) -> None:
        """Apply WavePlan from multi-form sources into rail state.

        Already-applied ``wave_slices`` win; otherwise diagnose dumps /
        ``wave_plan_path`` / architecture findings.
        """
        if state.wave_slices:
            return
        diagnosed = self._diagnose_job_wave_plan(state)
        if diagnosed.plan is None:
            return
        self._apply_wave_plan_unlocked(
            state,
            diagnosed.plan,
            source_path=diagnosed.source_path,
        )
        self._mirror_wave_plan_dumps_unlocked(state, diagnosed.plan)

    def _catalog_specs(self, state: RailJobState) -> list[dict[str, Any]]:
        """Flat slice specs from decompose_plan or synthetic from wave_slices."""
        if state.decompose_plan:
            return [dict(s) for s in state.decompose_plan if isinstance(s, dict)]
        out: list[dict[str, Any]] = []
        for name in state.wave_slices or []:
            sid = str(name).strip()
            if sid:
                out.append({"slice": sid, "description": sid, "tags": ["implementation", "maker"]})
        return out

    def _rebuild_spawned_slices(self, state: RailJobState) -> None:
        """Fill spawned_slices from maker annotations when empty (upgrade path)."""
        if state.spawned_slices:
            return
        for gid, ann in state.annotations.items():
            if ann.role != "maker" and "maker" not in ann.tags:
                continue
            if "implementation" not in ann.tags:
                continue
            slug = None
            for tag in ann.tags:
                if tag.startswith("slice:"):
                    slug = tag.split(":", 1)[1]
                    break
            if slug is None:
                # Prefer last non-generic tag as slice id.
                for tag in reversed(ann.tags):
                    if tag not in {
                        "implementation",
                        "maker",
                        "feedback",
                        "replant",
                    } and not tag.startswith("wave-"):
                        slug = tag
                        break
            if slug:
                state.spawned_slices[slug] = gid

    def ready_unspawned_slice_ids(self, state: RailJobState) -> list[str]:
        """Catalog slice ids ready to spawn (deps completed / omitted)."""
        self._rebuild_spawned_slices(state)
        specs = self._catalog_specs(state)
        ready: list[str] = []
        for spec in specs:
            slice_id = str(spec.get("slice") or "").strip()
            if not slice_id or slice_id in state.spawned_slices:
                continue
            deps = [str(d).strip() for d in (spec.get("depends_on") or []) if str(d).strip()]
            ok = True
            for dep in deps:
                gid = state.spawned_slices.get(dep)
                if not gid:
                    ok = False
                    break
                goal = self._ce._dag.get_goal(gid)
                if goal is None or goal.status != "completed":
                    ok = False
                    break
            if ok:
                ready.append(slice_id)
        return ready

    def has_ready_unspawned_slices(self, job_id: str) -> bool:
        """Structural helper for ``slices_ready_to_spawn`` guards."""
        state = self._jobs.get(job_id)
        if state is None:
            return False
        if not state.wave_slices and not state.decompose_plan:
            return False
        return bool(self.ready_unspawned_slice_ids(state))

    async def _do_spawn_wave_makers(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        """Spawn-ready makers for unspawned catalog slices (streaming; IG-732)."""
        del trigger_goal_id
        state = await self._require(job_id)
        self._ingest_job_wave_plan(state)
        self._rebuild_spawned_slices(state)

        if len(state.spawned_slices) >= state.effective_max_slices():
            return BuiltinResult(
                status="skipped",
                detail=f"max_slices={state.effective_max_slices()} reached",
            )

        resolution = resolve_fanout_slices(
            wave_slices=state.wave_slices,
            decompose_plan=state.decompose_plan,
            plan=None,
            max_slices=max(
                state.effective_max_slices(), state.effective_engine_max_parallel_goals()
            ),
            require_plan=state.require_plan,
        )
        if resolution.source == "missing_plan" or not resolution.slices:
            detail = resolution.detail or "LLM wave plan missing; refusing rigid defaults"
            logger.warning(
                "spawn_wave_makers skipped job=%s require_plan=%s detail=%s",
                job_id[:8],
                state.require_plan,
                detail,
            )
            return BuiltinResult(status="skipped", detail=detail)

        # Keep full catalog ids on state (do not shrink to a wave batch).
        if not state.wave_slices:
            state.wave_slices = list(resolution.slices)

        ready = self.ready_unspawned_slice_ids(state)
        # Expansion budget: only spawn until max_slices total.
        room = max(0, state.effective_max_slices() - len(state.spawned_slices))
        ready = ready[:room]
        if not ready:
            return BuiltinResult(
                status="skipped",
                detail="no ready unspawned slices",
            )

        arch_ids = [
            gid
            for gid, ann in state.annotations.items()
            if "architecture" in ann.tags
            and (g := self._ce._dag.get_goal(gid)) is not None
            and g.status == "completed"
        ]

        repo = _job_workspace(self._ce, job_id)
        if state.worktrees_enabled and repo is not None and _is_git_repo(repo):
            if not state.base_branch:
                state.base_branch = worktree_ops.detect_base_branch(repo)
            if not state.job_branch:
                # Avoid git ref nesting under maker branches job/<id>/<slug>.
                state.job_branch = f"job/{job_id[:8]}/_base"
            ensured = worktree_ops.ensure_job_branch(
                repo,
                job_branch=state.job_branch,
                base_branch=state.base_branch,
            )
            if not ensured.ok:
                logger.warning("ensure job branch failed job=%s: %s", job_id[:8], ensured.detail)

        spec_by_slice: dict[str, dict[str, Any]] = {}
        for spec in self._catalog_specs(state):
            key = str(spec.get("slice") or "").strip()
            if key:
                spec_by_slice[key] = spec

        created: list[str] = []
        logger.info(
            "spawn_wave_makers (spawn-ready) job=%s ready=%s spawned=%s budget=%s",
            job_id[:8],
            ready,
            list(state.spawned_slices),
            state.effective_max_slices(),
        )

        for slice_id in ready:
            slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in slice_id)[:48]
            slug = slug.strip("-") or f"slice-{len(created) + 1}"
            maker_ws: str | None = str(repo) if repo else None
            branch = f"job/{job_id[:8]}/{slug}"
            if state.worktrees_enabled and repo is not None and _is_git_repo(repo):
                wt = repo / ".soothe" / "worktrees" / slug
                start = state.job_branch or "HEAD"
                ensured_wt = worktree_ops.ensure_worktree(
                    repo, branch=branch, worktree_path=wt, start_point=start
                )
                if ensured_wt is not None:
                    maker_ws = str(ensured_wt)

            spec = spec_by_slice.get(slice_id) or spec_by_slice.get(slug) or {}
            ownership = str(spec.get("description") or "").strip()
            if not ownership:
                ownership = f"Implement only the '{slug}' slice ownership."
            priority = int(spec.get("priority") or 75)
            extra_tags = [
                str(t).strip()
                for t in (spec.get("tags") or [])
                if str(t).strip() and str(t).strip() not in {"implementation", "maker"}
            ]
            # CE depends: architecture + completed slice-dep makers.
            depends = list(arch_ids)
            for dep_slice in spec.get("depends_on") or []:
                dep_gid = state.spawned_slices.get(str(dep_slice).strip())
                if dep_gid and dep_gid not in depends:
                    depends.append(dep_gid)
            job_br = state.job_branch or f"job/{job_id[:8]}/_base"
            desc = (
                f"Slice maker [{slug}] for job {job_id}. "
                f"{ownership} "
                f"Work in workspace isolation (branch {branch}). "
                "Do not modify unrelated slices. Commit on this branch; "
                f"the host merges into {job_br} when you complete."
            )
            goal = await self._ce.create_goal(
                desc,
                parent_id=job_id,
                depends_on=depends or None,
                source="decomposition",
                priority=priority,
                workspace=maker_ws,
                rail_id=state.rail_id,
            )
            maker_tags = ["implementation", "maker", slug, f"slice:{slug}", *extra_tags]
            seen_tags: set[str] = set()
            maker_tags = [t for t in maker_tags if not (t in seen_tags or seen_tags.add(t))]
            await self.annotate_goal(
                goal.id,
                job_id,
                tags=maker_tags,
                role="maker",
                branch_id=branch,
            )
            state.spawned_slices[slice_id] = goal.id
            created.append(goal.id)

        # Trace counter only (not a spawn gate).
        if created:
            state.wave_index += 1
        await self._persist_job(state)

        root = await self._ce.get_goal(job_id)
        if root is not None and created:
            deps = list(root.depends_on or [])
            for gid in created:
                if gid not in deps:
                    deps.append(gid)
            await self._ce.update_dependencies(job_id, deps)

        detail = f"spawned {len(created)} ready makers slices={ready} source={resolution.source}"
        return BuiltinResult(
            status="success",
            detail=detail,
            created_goal_ids=created,
        )

    async def _do_spawn_integrate(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        """Spawn an agent integrate goal (custom rails only).

        Shipped greenfield/migration use host ``merge_branches`` instead.
        """
        state = await self._require(job_id)
        makers = [
            gid
            for gid, ann in state.annotations.items()
            if "implementation" in ann.tags
            and "feedback" not in ann.tags
            and ann.branch_status != "pruned"
            and (g := self._ce._dag.get_goal(gid)) is not None
            and g.status == "completed"
        ]
        if not makers and trigger_goal_id:
            makers = [trigger_goal_id]
        ws = _job_workspace(self._ce, job_id)
        job_br = state.job_branch or f"job/{job_id[:8]}/_base"
        goal = await self._ce.create_goal(
            (
                f"Integrate makers for job {job_id} into {job_br}. "
                "Prefer host merge when available; resolve remaining conflicts "
                "and leave a clean tree. Do not start unrelated features."
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
            tags=["integrate"],
            role="integrator",
            branch_id=job_br,
        )
        return BuiltinResult(
            status="success",
            detail=f"spawned integrate goal → {job_br}",
            created_goal_ids=[goal.id],
        )

    async def _do_commit_milestone(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        """Spawn git commit gate goal (custom rails; not greenfield merge path)."""
        state = await self._require(job_id)
        deps = [trigger_goal_id] if trigger_goal_id else []
        # Prefer integrate as dependency when present.
        integrates = [
            gid
            for gid, ann in state.annotations.items()
            if "integrate" in ann.tags
            and (g := self._ce._dag.get_goal(gid)) is not None
            and g.status == "completed"
        ]
        if integrates:
            deps = integrates
        ws = _job_workspace(self._ce, job_id)
        job_br = state.job_branch or f"job/{job_id[:8]}/_base"
        goal = await self._ce.create_goal(
            (
                f"Commit milestone for job {job_id} on {job_br}. "
                "Create one or more atomic git commits covering merged slices. "
                "Do not push unless asked. Leave `git log` / `git show` "
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
            tags=["commit", "milestone"],
            role="committer",
            branch_id=job_br,
        )
        return BuiltinResult(
            status="success",
            detail=f"spawned commit milestone on {job_br}",
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
        review_brief = resolve_verb_brief(
            "review",
            job_id=job_id,
            overrides=state.verb_overrides,
        )
        if not review_brief:
            return BuiltinResult(status="error", detail="review brief missing")
        goal = await self._ce.create_goal(
            review_brief,
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
        state = await self._require(job_id)
        brief = self._acceptance_brief_for_job(job_id)
        ws = _job_workspace(self._ce, job_id)
        goal = await self._ce.create_goal(
            (
                f"QA verify for job {job_id}. Run acceptance checks against "
                f"the job contract and report pass/fail with evidence.\n\n{brief}"
            ),
            parent_id=job_id,
            depends_on=deps or None,
            source="decomposition",
            priority=85,
            workspace=str(ws) if ws else None,
            rail_id=state.rail_id,
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
        """Spawn find→optimize→verify goals until acceptance (fan-out feedback)."""
        state = await self._require(job_id)
        if state.feedback_round >= state.max_feedback_rounds:
            return BuiltinResult(
                status="skipped",
                detail=f"max_feedback_rounds={state.max_feedback_rounds} reached",
            )
        root = self._ce._dag.get_goal(job_id)
        from soothe.autopilot.verify.job_maturity import latch_acceptance_met

        if latch_acceptance_met(
            rail_acceptance_met=state.acceptance_met,
            maturity=root.maturity if root is not None else None,
        ):
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
        await self._persist_job(state)
        ws = _job_workspace(self._ce, job_id)
        ws_str = str(ws) if ws else None
        # Never depend on the rail job root — it is never scheduled/completed.
        base_deps: list[str] = []
        if trigger_goal_id and trigger_goal_id != job_id:
            base_deps = [trigger_goal_id]

        diagnose = await self._ce.create_goal(
            (
                f"Feedback round {round_n} diagnose for job {job_id}. "
                "Find bugs, acceptance gaps, and regressions against the "
                "job acceptance contract. Produce a concrete defect "
                "list; do not implement fixes here.\n\n"
                f"{self._acceptance_brief_for_job(job_id)}"
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
                "findings and the job contract. Report remaining gaps; "
                "do not re-implement.\n\n"
                f"{self._acceptance_brief_for_job(job_id)}"
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

    async def _do_retry_maker(self, *, job_id: str, trigger_goal_id: str | None) -> BuiltinResult:
        """Replace a single failed maker; preserve completed siblings (IG-693)."""
        if not trigger_goal_id:
            return BuiltinResult(status="skipped", detail="no trigger maker")
        state = await self._require(job_id)
        failed = self._ce._dag.get_goal(trigger_goal_id)
        if failed is None:
            return BuiltinResult(status="error", detail="trigger maker missing")
        ann = state.annotations.get(trigger_goal_id, GoalAnnotation())
        tags = list(ann.tags or failed.rail_tags or [])
        if "maker" not in tags and "implementation" not in tags:
            return BuiltinResult(status="skipped", detail="trigger is not a maker")

        slug = next(
            (
                t
                for t in tags
                if t not in {"implementation", "maker", "replant"} and not t.startswith("wave-")
            ),
            "slice",
        )
        if failed.status not in TERMINAL_STATES:
            await self._ce.cancel_goal(trigger_goal_id, reason="rail:retry_maker_replace")
        await self.annotate_goal(trigger_goal_id, job_id, branch_status="pruned")

        arch_ids = [
            gid
            for gid, a in state.annotations.items()
            if "architecture" in a.tags
            and (g := self._ce._dag.get_goal(gid)) is not None
            and g.status == "completed"
        ]
        repo = _job_workspace(self._ce, job_id)
        maker_ws: str | None = str(repo) if repo else None
        if not state.job_branch:
            state.job_branch = f"job/{job_id[:8]}/_base"
        branch = f"job/{job_id[:8]}/{slug}-retry"
        if state.worktrees_enabled and repo is not None and _is_git_repo(repo):
            if not state.base_branch:
                state.base_branch = worktree_ops.detect_base_branch(repo)
            worktree_ops.ensure_job_branch(
                repo,
                job_branch=state.job_branch,
                base_branch=state.base_branch,
            )
            wt = repo / ".soothe" / "worktrees" / f"{slug}-retry"
            ensured = worktree_ops.ensure_worktree(
                repo,
                branch=branch,
                worktree_path=wt,
                start_point=state.job_branch,
            )
            if ensured is not None:
                maker_ws = str(ensured)

        desc = (
            f"Slice maker [{slug}] retry for job {job_id}. "
            f"Implement only the '{slug}' slice ownership. "
            f"Work in workspace isolation (branch {branch}). "
            "Do not modify unrelated slices. Commit on this branch; "
            f"the host merges into {state.job_branch} when you complete."
        )
        replacement = await self._ce.create_goal(
            desc,
            parent_id=job_id,
            depends_on=arch_ids or None,
            source="decomposition",
            priority=75,
            workspace=maker_ws,
            rail_id=state.rail_id,
            informs=[trigger_goal_id],
        )
        new_tags = ["implementation", "maker", slug, f"slice:{slug}", "replant"]
        state.spawned_slices[slug] = replacement.id
        await self._persist_job(state)
        await self.annotate_goal(
            replacement.id,
            job_id,
            tags=new_tags,
            role="maker",
            branch_id=branch,
        )

        root = await self._ce.get_goal(job_id)
        if root is not None:
            deps = [d for d in (root.depends_on or []) if d != trigger_goal_id]
            if replacement.id not in deps:
                deps.append(replacement.id)
            await self._ce.update_dependencies(job_id, deps)

        return BuiltinResult(
            status="success",
            detail=f"retried maker {slug} → {replacement.id}",
            created_goal_ids=[replacement.id],
        )

    async def _do_retry_architecture(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        """Replace a failed architecture/planner goal; clear stale wave plan."""
        if not trigger_goal_id:
            return BuiltinResult(status="skipped", detail="no trigger architecture")
        state = await self._require(job_id)
        failed = self._ce._dag.get_goal(trigger_goal_id)
        if failed is None:
            return BuiltinResult(status="error", detail="trigger architecture missing")
        ann = state.annotations.get(trigger_goal_id, GoalAnnotation())
        tags = list(ann.tags or failed.rail_tags or [])
        role = ann.role or failed.role
        if "architecture" not in tags and role != "planner":
            return BuiltinResult(status="skipped", detail="trigger is not architecture")

        if failed.status not in TERMINAL_STATES:
            await self._ce.cancel_goal(trigger_goal_id, reason="rail:retry_architecture_replace")
        await self.annotate_goal(trigger_goal_id, job_id, branch_status="pruned")

        # Stale slices must not unlock spawn_wave_makers without a new plan.
        async with self._lock:
            state = self._jobs.get(job_id)
            if state is not None:
                state.wave_slices = None
                state.decompose_plan = None
                state.wave_plan_source_path = None
                self._persist_rail_state_unlocked(state)

        # Prefer catalog ``do:`` / brief overrides via invoke (not a direct _do_*).
        result = await self.invoke("plan_milestones", job_id=job_id, trigger_goal_id=None)
        if result.status != "success" or not result.created_goal_ids:
            return result

        new_arch_id = result.created_goal_ids[0]
        root = await self._ce.get_goal(job_id)
        if root is not None:
            deps = [d for d in (root.depends_on or []) if d != trigger_goal_id]
            if new_arch_id not in deps:
                deps.append(new_arch_id)
            await self._ce.update_dependencies(job_id, deps)

        return BuiltinResult(
            status="success",
            detail=f"retried architecture → {new_arch_id}",
            created_goal_ids=[new_arch_id],
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

    def unmerged_maker_ids(self, job_id: str) -> list[str]:
        """Completed wave makers still needing host merge (oldest first)."""
        state = self._jobs.get(job_id)
        if state is None:
            return []
        out: list[str] = []
        for gid, ann in state.annotations.items():
            tags = ann.tags or []
            if "implementation" not in tags or "feedback" in tags:
                continue
            if "resolve" in tags:
                continue
            if ann.branch_status not in {"active", "conflict"}:
                continue
            goal = self._ce._dag.get_goal(gid)
            if goal is None or goal.status != "completed":
                continue
            out.append(gid)

        # Stable: created_at when available, else id.
        def _key(gid: str) -> tuple[str, str]:
            g = self._ce._dag.get_goal(gid)
            created = getattr(g, "created_at", None) or ""
            return (str(created), gid)

        out.sort(key=_key)
        return out

    def resolve_inflight_for_maker(self, job_id: str, maker_id: str) -> str | None:
        """Return pending/active resolve+merge goal id for ``maker_id``, if any."""
        state = self._jobs.get(job_id)
        if state is None:
            return None
        for gid, ann in state.annotations.items():
            tags = set(ann.tags or [])
            if "resolve" not in tags or "merge" not in tags:
                continue
            goal = self._ce._dag.get_goal(gid)
            if goal is None or goal.status not in {"pending", "active"}:
                continue
            deps = list(goal.depends_on or [])
            informs = list(getattr(goal, "informs", None) or [])
            if maker_id in deps or maker_id in informs:
                return gid
            # Also match when brief/workspace lineage uses same branch_id.
            if ann.branch_id and state.annotations.get(maker_id):
                maker_ann = state.annotations[maker_id]
                if maker_ann.branch_id and ann.branch_id == maker_ann.branch_id:
                    return gid
        return None

    def _maker_id_for_resolve_trigger(
        self, state: RailJobState, trigger_goal_id: str
    ) -> str | None:
        """If trigger is a resolve goal, return the maker it should re-merge."""
        ann = state.annotations.get(trigger_goal_id)
        if ann is None:
            return None
        tags = set(ann.tags or [])
        if "resolve" not in tags or "merge" not in tags:
            return None
        goal = self._ce._dag.get_goal(trigger_goal_id)
        if goal is None:
            return None
        for dep in list(goal.depends_on or []):
            dann = state.annotations.get(dep)
            if (
                dann is not None
                and "implementation" in (dann.tags or [])
                and "resolve" not in (dann.tags or [])
            ):
                return dep
        # Fall back: maker with matching branch_id still unmerged.
        if ann.branch_id:
            for gid, other in state.annotations.items():
                if other.branch_id == ann.branch_id and "implementation" in (other.tags or []):
                    if "resolve" not in (other.tags or []) and other.branch_status in {
                        "active",
                        "conflict",
                    }:
                        return gid
        return None

    async def _spawn_merge_resolve_goal(
        self,
        *,
        job_id: str,
        state: RailJobState,
        maker_id: str,
        branch: str,
        detail: str,
        workspace: str | None,
    ) -> str:
        """Spawn or reuse a trivial StrangeLoop resolve goal for host merge failure."""
        existing = self.resolve_inflight_for_maker(job_id, maker_id)
        if existing is not None:
            return existing
        job_branch = state.job_branch or f"job/{job_id[:8]}/_base"
        brief = (
            f"Integrate maker branch {branch} into {job_branch} for job {job_id[:8]}. "
            f"Workspace: {workspace or 'repo root'}. "
            f"Host merge failed: {detail[:400]}. "
            "Use git/tools to commit any uncommitted slice work, fix conflicts, "
            f"leave {job_branch} containing the slice tip, then complete. "
            "Do not re-implement features."
        )
        resolve = await self._ce.create_goal(
            brief,
            parent_id=job_id,
            depends_on=[maker_id],
            source="decomposition",
            priority=85,
            workspace=workspace,
            rail_id=state.rail_id,
        )
        await self.annotate_goal(
            resolve.id,
            job_id,
            tags=["resolve", "merge", "implementation"],
            role="resolver",
            branch_id=branch,
            branch_status="conflict",
        )
        await self.annotate_goal(maker_id, job_id, branch_status="conflict")
        root = await self._ce.get_goal(job_id)
        if root is not None:
            deps = list(root.depends_on or [])
            if resolve.id not in deps:
                deps.append(resolve.id)
            await self._ce.update_dependencies(job_id, deps)
        return resolve.id

    async def _do_merge_branches(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        """Host-merge completed maker into job branch; refresh peers; spawn review.

        Happy-path git merge only. Conflicts / complex failures spawn a resolve
        StrangeLoop goal instead of wedging the rail with a bare error.
        """
        state = await self._require(job_id)

        maker_id: str | None = None
        if trigger_goal_id:
            # Resolve completion → retry merge for its maker.
            resolved_maker = self._maker_id_for_resolve_trigger(state, trigger_goal_id)
            if resolved_maker is not None:
                maker_id = resolved_maker
            else:
                ann = state.annotations.get(trigger_goal_id)
                if (
                    ann is not None
                    and "implementation" in (ann.tags or [])
                    and "resolve" not in (ann.tags or [])
                    and "feedback" not in (ann.tags or [])
                    and ann.branch_status not in {"merged", "pruned"}
                ):
                    maker = self._ce._dag.get_goal(trigger_goal_id)
                    if maker is not None and maker.status == "completed":
                        maker_id = trigger_goal_id

        if maker_id is None:
            # dag_idle / non-maker trigger: pick oldest unmerged without resolve inflight.
            for cand in self.unmerged_maker_ids(job_id):
                if self.resolve_inflight_for_maker(job_id, cand) is None:
                    maker_id = cand
                    break
            if maker_id is None:
                return BuiltinResult(
                    status="skipped",
                    detail="no unmerged maker ready (resolve inflight or none)",
                )

        ann = state.annotations.get(maker_id)
        if ann is None or "implementation" not in ann.tags:
            return BuiltinResult(status="skipped", detail="trigger is not an implementation maker")
        if ann.branch_status in {"merged", "pruned"}:
            return BuiltinResult(status="skipped", detail=f"already {ann.branch_status}")
        maker = self._ce._dag.get_goal(maker_id)
        if maker is None or maker.status != "completed":
            return BuiltinResult(status="skipped", detail="maker not completed")

        # Skip while a resolve worker is already active (completed resolve → not inflight).
        inflight = self.resolve_inflight_for_maker(job_id, maker_id)
        if inflight is not None:
            return BuiltinResult(
                status="skipped",
                detail=f"resolve inflight for maker: {inflight[:8]}",
                created_goal_ids=[inflight],
            )

        created: list[str] = []
        repo = _job_workspace(self._ce, job_id)
        branch = ann.branch_id
        merge_detail = "no-git merge skipped"

        if state.worktrees_enabled and repo is not None and _is_git_repo(repo) and branch:
            if not state.base_branch:
                state.base_branch = worktree_ops.detect_base_branch(repo)
            if not state.job_branch:
                state.job_branch = f"job/{job_id[:8]}/_base"
            maker_wt = Path(maker.workspace) if maker.workspace else None
            result = await asyncio.to_thread(
                worktree_ops.merge_branch_into,
                repo,
                target_branch=state.job_branch,
                source_branch=branch,
                maker_worktree=maker_wt,
                base_branch=state.base_branch,
            )
            if not result.ok:
                resolve_id = await self._spawn_merge_resolve_goal(
                    job_id=job_id,
                    state=state,
                    maker_id=maker_id,
                    branch=branch,
                    detail=result.detail or "host merge failed",
                    workspace=str(maker.workspace or repo),
                )
                await self._persist_job(state)
                return BuiltinResult(
                    status="success",
                    detail=result.detail,
                    created_goal_ids=[resolve_id],
                )
            merge_detail = result.detail
            # Refresh other active maker worktrees.
            for gid, other in state.annotations.items():
                if gid == maker_id or "implementation" not in other.tags:
                    continue
                if other.branch_status in {"merged", "pruned", "conflict"}:
                    continue
                g = self._ce._dag.get_goal(gid)
                if g is None or not g.workspace:
                    continue
                wt = Path(g.workspace)
                if wt.exists():
                    await asyncio.to_thread(
                        worktree_ops.refresh_worktree_onto,
                        wt,
                        onto_branch=state.job_branch,
                    )
        else:
            # Non-git / worktrees disabled: still mark merged for streaming spawn.
            merge_detail = "annotated merged (git worktrees disabled or unavailable)"

        await self.annotate_goal(maker_id, job_id, branch_status="merged")
        await self._persist_job(state)

        # Per-maker review (does not block unrelated makers).
        review = await self._ce.create_goal(
            (
                f"Review merged slice for maker {maker_id[:8]} on "
                f"{state.job_branch or 'job branch'}. Diff-scoped review only; "
                "do not block unrelated slices."
            ),
            parent_id=job_id,
            depends_on=[maker_id],
            source="decomposition",
            priority=80,
            workspace=str(repo) if repo else None,
            rail_id=state.rail_id,
        )
        await self.annotate_goal(
            review.id,
            job_id,
            tags=["review"],
            role="reviewer",
            branch_id=state.job_branch or job_id,
        )
        created.append(review.id)

        # Grow the CE DAG with newly unblocked slices.
        spawn = await self.invoke(
            "spawn_wave_makers",
            job_id=job_id,
            trigger_goal_id=maker_id,
        )
        created.extend(list(spawn.created_goal_ids or []))

        root = await self._ce.get_goal(job_id)
        if root is not None:
            deps = list(root.depends_on or [])
            for gid in created:
                if gid not in deps:
                    deps.append(gid)
            await self._ce.update_dependencies(job_id, deps)

        return BuiltinResult(
            status="success",
            detail=f"{merge_detail}; spawn={spawn.detail}",
            created_goal_ids=created,
        )

    async def _do_land_job_branch(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        """Merge job branch into base branch (main/master)."""
        del trigger_goal_id
        state = await self._require(job_id)
        repo = _job_workspace(self._ce, job_id)
        if repo is None or not _is_git_repo(repo) or not state.job_branch:
            return BuiltinResult(
                status="skipped",
                detail="land skipped (no git repo or job_branch)",
            )
        if not state.base_branch:
            state.base_branch = worktree_ops.detect_base_branch(repo)
        result = await asyncio.to_thread(
            worktree_ops.land_job_branch,
            repo,
            job_branch=state.job_branch,
            base_branch=state.base_branch,
        )
        await self._persist_job(state)
        if result.conflict:
            resolve = await self._ce.create_goal(
                (
                    f"Resolve land conflict merging {state.job_branch} into "
                    f"{state.base_branch} for job {job_id}."
                ),
                parent_id=job_id,
                source="decomposition",
                priority=90,
                workspace=str(repo),
                rail_id=state.rail_id,
            )
            await self.annotate_goal(
                resolve.id,
                job_id,
                tags=["resolve", "land"],
                role="resolver",
                branch_id=state.job_branch,
                branch_status="conflict",
            )
            return BuiltinResult(
                status="success",
                detail=result.detail,
                created_goal_ids=[resolve.id],
            )
        if not result.ok:
            return BuiltinResult(status="error", detail=result.detail)
        return BuiltinResult(status="success", detail=result.detail)

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
        # Final land onto base branch before completing the root.
        land = await self._do_land_job_branch(job_id=job_id, trigger_goal_id=trigger_goal_id)
        if land.status == "error":
            return land
        if land.created_goal_ids:
            return BuiltinResult(
                status="success",
                detail=f"land blocked on resolve: {land.detail}",
                created_goal_ids=list(land.created_goal_ids),
            )
        root = await self._ce.get_goal(job_id)
        if root is None:
            return BuiltinResult(status="error", detail="job root missing")
        if root.status not in TERMINAL_STATES:
            await self._ce.complete_goal(job_id)
        state.completed = True
        state.suspended = False
        await self._persist_job(state)
        return BuiltinResult(
            status="success",
            detail=f"job completed; land={land.detail or land.status}",
        )

    async def _require(self, job_id: str) -> RailJobState:
        async with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                msg = f"job {job_id} not bound to rail builtins"
                raise KeyError(msg)
            return state

    async def descendant_goals(self, job_id: str) -> list[GoalNode]:
        """Direct job children + root (same scope as ``_job_descendants``)."""
        return self._job_descendants(job_id)
