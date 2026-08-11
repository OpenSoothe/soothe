"""Rail Exec L0 recipe runner (RFC-231 M3 / IG-717).

Runs catalog verb ``do:`` lists as closed CE primitives. Unknown ops are
rejected at catalog load time; this module assumes validated steps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from soothe.autopilot.rails.builtins_exec import (
    BuiltinResult,
    RailBuiltinExecutor,
    RailJobState,
    _job_workspace,
)
from soothe.autopilot.rails.l0_schema import L0_OPS
from soothe.autopilot.rails.verb_defaults import (
    apply_planner_waveplan_hints,
    interpolate_brief,
)
from soothe.context.models import TERMINAL_STATES

logger = logging.getLogger(__name__)


@dataclass
class _RecipeCtx:
    job_id: str
    trigger_goal_id: str | None
    state: RailJobState
    step_ids: dict[str, str] = field(default_factory=dict)
    created: list[str] = field(default_factory=list)
    skipped_detail: str | None = None


def interpolate_recipe_text(template: str, ctx: _RecipeCtx) -> str:
    """Replace ``{key}`` / ``${key}`` for job counters and ``{job_id}``."""
    text = interpolate_brief(template, job_id=ctx.job_id)
    replacements = {
        "feedback_round": str(ctx.state.feedback_round),
        "wave_index": str(ctx.state.wave_index),
        "job_id": ctx.job_id,
    }
    for key, value in replacements.items():
        text = text.replace(f"{{{key}}}", value)
        text = text.replace(f"${{{key}}}", value)
        text = text.replace(f"${key}", value)
    return text


def _resolve_ref(ref: str, ctx: _RecipeCtx) -> str | None:
    name = ref.strip()
    if not name:
        return None
    if name == "trigger":
        return ctx.trigger_goal_id
    if name == "self":
        return ctx.created[-1] if ctx.created else None
    if name in ctx.step_ids:
        return ctx.step_ids[name]
    # Allow raw goal ids already known.
    return name


def _resolve_ref_list(refs: Any, ctx: _RecipeCtx) -> list[str]:
    if refs is None:
        return []
    if isinstance(refs, str):
        refs = [refs]
    if not isinstance(refs, list):
        return []
    out: list[str] = []
    for ref in refs:
        gid = _resolve_ref(str(ref), ctx)
        if gid and gid not in out:
            out.append(gid)
    return out


class RecipeRunner:
    """Execute a validated ``do:`` list against ``RailBuiltinExecutor`` helpers."""

    def __init__(self, executor: RailBuiltinExecutor) -> None:
        self._ex = executor

    async def run(
        self,
        steps: list[dict[str, Any]],
        *,
        job_id: str,
        trigger_goal_id: str | None,
    ) -> BuiltinResult:
        state = await self._ex._require(job_id)
        ctx = _RecipeCtx(job_id=job_id, trigger_goal_id=trigger_goal_id, state=state)
        try:
            for i, step in enumerate(steps):
                if ctx.skipped_detail is not None:
                    break
                if not isinstance(step, dict) or len(step) != 1:
                    return BuiltinResult(
                        status="error",
                        detail=f"recipe step[{i}] must be a single-key mapping",
                    )
                op, spec = next(iter(step.items()))
                handler = getattr(self, f"_op_{op}", None)
                if handler is None:
                    return BuiltinResult(status="error", detail=f"unknown L0 op: {op}")
                await handler(spec if spec is not None else {}, ctx)
        except Exception as exc:
            logger.exception("Rail recipe failed job=%s", job_id[:8])
            return BuiltinResult(
                status="error",
                detail=f"{type(exc).__name__}: recipe failed",
            )

        if ctx.skipped_detail is not None:
            return BuiltinResult(status="skipped", detail=ctx.skipped_detail)
        return BuiltinResult(
            status="success",
            detail=f"recipe spawned {len(ctx.created)} goal(s)",
            created_goal_ids=list(ctx.created),
        )

    async def _op_gate(self, spec: Any, ctx: _RecipeCtx) -> None:
        if not isinstance(spec, dict):
            spec = {}
        unless = str(spec.get("unless") or "").strip()
        if unless == "acceptance_met" and ctx.state.acceptance_met:
            ctx.skipped_detail = "acceptance already met"
            return
        max_key = spec.get("max")
        if max_key == "feedback_rounds":
            if ctx.state.feedback_round >= ctx.state.max_feedback_rounds:
                ctx.skipped_detail = f"max_feedback_rounds={ctx.state.max_feedback_rounds} reached"
                return
        elif max_key == "waves":
            # Expansion budget (legacy gate name); IG-732 uses spawned count.
            if len(ctx.state.spawned_slices) >= ctx.state.effective_max_slices():
                ctx.skipped_detail = f"max_slices={ctx.state.effective_max_slices()} reached"
                return
        inflight = str(spec.get("no_inflight") or "").strip()
        if inflight == "feedback":
            for gid, ann in ctx.state.annotations.items():
                if "feedback" not in (ann.tags or []):
                    continue
                g = self._ex._ce._dag.get_goal(gid)
                if g is not None and g.status not in TERMINAL_STATES:
                    ctx.skipped_detail = f"feedback inflight: {gid}"
                    return

    async def _op_bump(self, spec: Any, ctx: _RecipeCtx) -> None:
        if isinstance(spec, str):
            counter = spec.strip()
        elif isinstance(spec, dict):
            counter = str(spec.get("counter") or "").strip()
        else:
            counter = ""
        if counter == "feedback_round":
            ctx.state.feedback_round += 1
        elif counter == "wave_index":
            ctx.state.wave_index += 1
        else:
            raise ValueError(f"unsupported bump counter: {counter!r}")
        await self._ex._persist_job(ctx.state)

    async def _op_spawn_goal(self, spec: Any, ctx: _RecipeCtx) -> None:
        if not isinstance(spec, dict):
            raise ValueError("spawn_goal spec must be a mapping")
        brief_raw = spec.get("brief")
        if not isinstance(brief_raw, str) or not brief_raw.strip():
            raise ValueError("spawn_goal.brief is required")
        brief = interpolate_recipe_text(brief_raw, ctx)
        tags_raw = spec.get("tags") or []
        if not isinstance(tags_raw, list):
            raise ValueError("spawn_goal.tags must be a list")
        tags = [interpolate_recipe_text(str(t), ctx) for t in tags_raw]
        # Architecture/milestones planners share WavePlan SoT (verb_defaults).
        if "architecture" in tags and "milestones" in tags:
            brief = apply_planner_waveplan_hints(brief)
        role = spec.get("role")
        role_s = str(role).strip() if isinstance(role, str) and role.strip() else None
        priority = int(spec.get("priority") or 70)
        depends = _resolve_ref_list(spec.get("depends"), ctx)
        # Never depend on job root.
        depends = [d for d in depends if d != ctx.job_id]

        intake_scope = spec.get("intake_scope")
        intake_scope_s: str | None = None
        if isinstance(intake_scope, str) and intake_scope.strip():
            intake_scope_s = intake_scope.strip().lower()
            if intake_scope_s not in {"trivial", "simple", "complex"}:
                raise ValueError(
                    f"spawn_goal.intake_scope must be trivial|simple|complex; got {intake_scope!r}"
                )

        ws = _job_workspace(self._ex._ce, ctx.job_id)
        goal = await self._ex._ce.create_goal(
            brief,
            parent_id=ctx.job_id,
            depends_on=depends or None,
            source="decomposition",
            priority=priority,
            workspace=str(ws) if ws else None,
            rail_id=ctx.state.rail_id,
            intake_scope=intake_scope_s,
        )
        await self._ex.annotate_goal(
            goal.id,
            ctx.job_id,
            tags=tags,
            role=role_s,
            branch_id=ctx.job_id,
        )
        ctx.created.append(goal.id)
        step_id = spec.get("id")
        if isinstance(step_id, str) and step_id.strip():
            ctx.step_ids[step_id.strip()] = goal.id

        wire = spec.get("wire")
        if isinstance(wire, dict) and wire.get("root_waits_on") is not None:
            await self._root_waits_on(wire.get("root_waits_on"), ctx, default_self=goal.id)

    async def _op_wire_deps(self, spec: Any, ctx: _RecipeCtx) -> None:
        if not isinstance(spec, dict):
            raise ValueError("wire_deps spec must be a mapping")
        await self._root_waits_on(spec.get("root_waits_on"), ctx, default_self=None)

    async def _root_waits_on(
        self,
        refs: Any,
        ctx: _RecipeCtx,
        *,
        default_self: str | None,
    ) -> None:
        if refs == "self" or refs is True:
            gids = [default_self] if default_self else _resolve_ref_list(["self"], ctx)
        else:
            gids = _resolve_ref_list(refs, ctx)
        gids = [g for g in gids if g and g != ctx.job_id]
        if not gids:
            return
        root = await self._ex._ce.get_goal(ctx.job_id)
        if root is None:
            return
        deps = list(root.depends_on or [])
        for gid in gids:
            if gid not in deps:
                deps.append(gid)
        await self._ex._ce.update_dependencies(ctx.job_id, deps)

    async def _op_pause_job(self, spec: Any, ctx: _RecipeCtx) -> None:
        del spec
        result = await self._ex._do_pause_for_user(
            job_id=ctx.job_id, trigger_goal_id=ctx.trigger_goal_id
        )
        if result.status != "success":
            ctx.skipped_detail = result.detail or result.status

    async def _op_complete_job(self, spec: Any, ctx: _RecipeCtx) -> None:
        del spec
        # Delegate to existing builtin for maturity gates.
        result = await self._ex._do_complete_job(
            job_id=ctx.job_id, trigger_goal_id=ctx.trigger_goal_id
        )
        if result.status != "success":
            ctx.skipped_detail = result.detail or result.status
            return
        ctx.created.extend(result.created_goal_ids)


__all__ = ["L0_OPS", "RecipeRunner"]
