"""Plan evaluate station (IG-672): inventory (gap) then assess in one stem node.

Logical subgraph phases (parent LangGraph station ``evaluate``):

1. optional inventory (``PlanGapAnalysis``) — sequential or parallel facets
2. assess (``StatusAssessment``) + existing terminal / keep routing

Inventory soft-fails into assess-without-map; assess drives parent routes.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Literal

from soothe.sloop.goal_text import resolve_planning_goal
from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.prompts.plan_ledger_projection import (
    _current_goal_has_execute_ledger,
    resolve_planner_projection_mode,
)
from soothe.sloop.stages.plan.assess import node_plan_assess
from soothe.sloop.stages.plan.phase_status import emit_plan_phase_status
from soothe.sloop.state.schemas import GoalComponentStatus, PlanGapAnalysis

logger = logging.getLogger(__name__)

_PLAN_EVALUATE_STATUS_LABEL = "Evaluating progress"
_PLAN_GAP_STATUS_LABEL = "Analyzing coverage"

_DEFAULT_WALL_CLOCK = 90.0
_DEFAULT_LEG_TIMEOUT = 45.0
_DEFAULT_MAX_CONCURRENCY = 4
_DEFAULT_MIN_FACETS = 2
_MAX_FACETS = 8

# Structural delimiter split for goal_description / GOAL seeds (IG-557 / IG-672).
_FACET_SPLIT_RE = re.compile(r"[\n;]+|(?:\d+[\).\]]\s+)|(?:[-*]\s+)")


def _loop_cfg(ctx: LoopRuntimeContext) -> Any | None:
    cfg = getattr(ctx.strange_loop, "config", None)
    if cfg is None:
        return None
    return getattr(cfg.agent, "loop", None)


def _gap_mode(ctx: LoopRuntimeContext) -> Literal["sequential", "parallel"]:
    loop = _loop_cfg(ctx)
    if loop is None:
        return "sequential"
    mode = getattr(loop, "plan_evaluate_gap_mode", "sequential")
    return "parallel" if mode == "parallel" else "sequential"


def _wall_clock_seconds(ctx: LoopRuntimeContext) -> float:
    loop = _loop_cfg(ctx)
    if loop is None:
        return _DEFAULT_WALL_CLOCK
    try:
        return float(loop.plan_evaluate_gap_wall_clock_seconds)
    except Exception:
        return _DEFAULT_WALL_CLOCK


def _leg_timeout_seconds(ctx: LoopRuntimeContext) -> float:
    loop = _loop_cfg(ctx)
    if loop is None:
        return _DEFAULT_LEG_TIMEOUT
    try:
        return float(loop.plan_evaluate_gap_leg_timeout_seconds)
    except Exception:
        return _DEFAULT_LEG_TIMEOUT


def _max_concurrency(ctx: LoopRuntimeContext) -> int:
    loop = _loop_cfg(ctx)
    if loop is None:
        return _DEFAULT_MAX_CONCURRENCY
    try:
        return max(1, min(_MAX_FACETS, int(loop.plan_evaluate_gap_max_concurrency)))
    except Exception:
        return _DEFAULT_MAX_CONCURRENCY


def _min_facets(ctx: LoopRuntimeContext) -> int:
    loop = _loop_cfg(ctx)
    if loop is None:
        return _DEFAULT_MIN_FACETS
    try:
        return max(2, min(_MAX_FACETS, int(loop.plan_evaluate_gap_min_facets)))
    except Exception:
        return _DEFAULT_MIN_FACETS


def should_run_inventory(ctx: LoopRuntimeContext) -> bool:
    """True when evaluate should run gap inventory before assess.

    Inventory is always enabled for applicable mid-goal paths (IG-672). Skips
    are structural only: trivial intake, or new_goal with no execute evidence.
    """
    state = ctx.loop_state
    intake = getattr(state.intent, "intake_label", None) if state.intent is not None else None
    if intake == IntakeLabel.TRIVIAL:
        return False
    mode = resolve_planner_projection_mode(state)
    if (
        mode == "new_goal"
        and not state.step_results
        and not _current_goal_has_execute_ledger(state)
    ):
        logger.info("[Plan] evaluate inventory skipped (reason=iter0_no_execution)")
        return False
    return True


def seed_inventory_facets(ctx: LoopRuntimeContext) -> list[str]:
    """Deterministic facet labels for parallel inventory (IG-672)."""
    state = ctx.loop_state
    seeds: list[str] = []

    if ctx.ce is not None and ctx.ce_goal_id:
        try:
            getter = getattr(ctx.ce, "get_goal_sync", None) or getattr(ctx.ce, "get_goal", None)
            goal_node = getter(ctx.ce_goal_id) if callable(getter) else None
            if asyncio.iscoroutine(goal_node):
                goal_node = None  # never block seeding on async lookup
            prior = getattr(goal_node, "last_gap_analysis", None) if goal_node else None
            if isinstance(prior, dict):
                components = prior.get("components")
                if isinstance(components, list):
                    for item in components:
                        if not isinstance(item, dict):
                            continue
                        name = item.get("component")
                        if isinstance(name, str) and name.strip():
                            seeds.append(name.strip()[:120])
            elif prior is not None:
                for comp in getattr(prior, "components", []) or []:
                    name = getattr(comp, "component", None)
                    if isinstance(name, str) and name.strip():
                        seeds.append(name.strip()[:120])
        except Exception:
            logger.debug("[Plan] evaluate facet seed from CE failed", exc_info=True)

    if not seeds:
        intent = state.intent
        raw = ""
        if intent is not None:
            raw = (getattr(intent, "goal_description", None) or "").strip()
        if not raw:
            raw = (state.goal or "").strip()
        parts = [p.strip() for p in _FACET_SPLIT_RE.split(raw) if p and p.strip()]
        # Drop tiny fragments; keep ordered unique.
        seen: set[str] = set()
        for part in parts:
            if len(part) < 3:
                continue
            key = part.lower()
            if key in seen:
                continue
            seen.add(key)
            seeds.append(part[:120])
            if len(seeds) >= _MAX_FACETS:
                break

    if not seeds:
        goal = (resolve_planning_goal(state) or state.goal or "goal").strip()
        seeds = [goal[:120] or "goal"]
    return seeds[:_MAX_FACETS]


def _distance_from_components(
    components: list[GoalComponentStatus],
) -> Literal["far", "moderate", "near", "at_goal"]:
    if not components:
        return "moderate"
    statuses = {c.status for c in components}
    if statuses <= {"satisfied"}:
        return "at_goal"
    if "blocked" in statuses or "not_started" in statuses:
        if all(c.status in ("not_started", "blocked") for c in components):
            return "far"
        return "moderate"
    if statuses <= {"satisfied", "partial"}:
        satisfied = sum(1 for c in components if c.status == "satisfied")
        if satisfied >= max(1, len(components) - 1):
            return "near"
        return "moderate"
    return "moderate"


def reduce_component_legs(
    facets: list[str],
    legs: list[GoalComponentStatus | None],
) -> PlanGapAnalysis | None:
    """Merge parallel facet legs into PlanGapAnalysis.

    Missing legs become ``not_started`` and block ``at_goal``.
    """
    if not facets:
        return None
    components: list[GoalComponentStatus] = []
    for i, facet in enumerate(facets):
        leg = legs[i] if i < len(legs) else None
        if leg is None:
            components.append(
                GoalComponentStatus(
                    component=facet,
                    status="not_started",
                    evidence="",
                    gap="inventory leg missing or timed out",
                )
            )
        else:
            components.append(leg.model_copy(update={"component": leg.component or facet}))

    open_gaps = [
        (c.gap or c.component).strip()
        for c in components
        if c.status in ("not_started", "partial", "blocked") and (c.gap or c.component)
    ][:6]
    evidence_bits = [c.evidence.strip() for c in components if c.evidence.strip()]
    evidence_summary = "; ".join(evidence_bits)[:2048] or "see components"
    distance = _distance_from_components(components)
    # Any missing/failed leg already encoded as not_started → cannot be at_goal
    # unless every component is satisfied (reduce rule).
    gap_reasoning = (f"I mapped {len(components)} goal facet(s); distance is {distance}.")[:2048]
    return PlanGapAnalysis(
        components=components,
        evidence_summary=evidence_summary,
        remaining_gaps=open_gaps,
        distance_from_goal=distance,
        gap_reasoning=gap_reasoning,
    )


async def _run_sequential_inventory(ctx: LoopRuntimeContext) -> PlanGapAnalysis | None:
    strange_loop = ctx.strange_loop
    state = ctx.loop_state
    context = strange_loop._build_plan_context(state)
    wall = _wall_clock_seconds(ctx)
    try:
        gap = await asyncio.wait_for(
            strange_loop.plan_phase.analyze_plan_gap(
                goal=resolve_planning_goal(state),
                state=state,
                context=context,
                context_engine=ctx.ce,
            ),
            timeout=wall,
        )
    except TimeoutError as exc:
        logger.warning(
            "[Plan] evaluate inventory exceeded %.0fs wall clock; continuing without gap map: %s",
            wall,
            str(exc)[:240] or type(exc).__name__,
        )
        return None
    except Exception as exc:
        logger.warning(
            "[Plan] evaluate inventory failed; continuing without gap map: %s: %s",
            type(exc).__name__,
            str(exc)[:240],
        )
        return None
    return gap


async def _analyze_one_facet(
    ctx: LoopRuntimeContext,
    *,
    facet: str,
    leg_index: int,
    timeout: float,
) -> GoalComponentStatus | None:
    strange_loop = ctx.strange_loop
    state = ctx.loop_state
    context = strange_loop._build_plan_context(state)
    try:
        return await asyncio.wait_for(
            strange_loop.plan_phase.analyze_plan_gap_component(
                goal=resolve_planning_goal(state),
                state=state,
                context=context,
                component=facet,
                context_engine=ctx.ce,
                leg_index=leg_index,
            ),
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning(
            "[Plan] evaluate facet leg failed (%s): %s: %s",
            facet[:80],
            type(exc).__name__,
            str(exc)[:200],
        )
        return None


async def _run_parallel_inventory(
    ctx: LoopRuntimeContext,
    facets: list[str],
) -> PlanGapAnalysis | None:
    wall = _wall_clock_seconds(ctx)
    leg_timeout = min(_leg_timeout_seconds(ctx), wall)
    concurrency = _max_concurrency(ctx)
    sem = asyncio.Semaphore(concurrency)
    t0 = time.perf_counter()

    async def _bounded(facet: str, leg_index: int) -> GoalComponentStatus | None:
        async with sem:
            remaining = wall - (time.perf_counter() - t0)
            if remaining <= 0.05:
                return None
            return await _analyze_one_facet(
                ctx,
                facet=facet,
                leg_index=leg_index,
                timeout=min(leg_timeout, remaining),
            )

    try:
        legs = await asyncio.wait_for(
            asyncio.gather(*[_bounded(f, i) for i, f in enumerate(facets)]),
            timeout=wall,
        )
    except TimeoutError:
        logger.warning(
            "[Plan] evaluate parallel inventory exceeded %.0fs wall clock",
            wall,
        )
        legs = [None] * len(facets)

    ok = sum(1 for leg in legs if leg is not None)
    logger.info(
        "[Plan] phase=evaluate-gap mode=parallel facets=%d ok_legs=%d/%d elapsed_ms=%.0f iter=%d",
        len(facets),
        ok,
        len(facets),
        (time.perf_counter() - t0) * 1000,
        ctx.loop_state.iteration,
    )
    return reduce_component_legs(facets, list(legs))


async def run_inventory(ctx: LoopRuntimeContext) -> PlanGapAnalysis | None:
    """Run gap inventory (sequential or parallel) and return PlanGapAnalysis or None."""
    await emit_plan_phase_status(ctx, label=_PLAN_GAP_STATUS_LABEL)
    mode = _gap_mode(ctx)
    facets = seed_inventory_facets(ctx)
    min_facets = _min_facets(ctx)

    if mode == "parallel" and len(facets) >= min_facets:
        gap = await _run_parallel_inventory(ctx, facets)
        if gap is not None:
            return gap
        logger.info("[Plan] parallel inventory empty; falling back to sequential")

    t0 = time.perf_counter()
    gap = await _run_sequential_inventory(ctx)
    logger.info(
        "[Plan] phase=evaluate-gap mode=sequential facets=%d ok_legs=%d/%d elapsed_ms=%.0f iter=%d",
        1,
        1 if gap is not None else 0,
        1,
        (time.perf_counter() - t0) * 1000,
        ctx.loop_state.iteration,
    )
    return gap


def _loop_planner(ctx: LoopRuntimeContext) -> Any:
    """Return the underlying LLMPlanner when available (for Langfuse pin)."""
    strange_loop = ctx.strange_loop
    planner = getattr(strange_loop, "loop_planner", None)
    if planner is not None:
        return planner
    phase = getattr(strange_loop, "plan_phase", None)
    return getattr(phase, "_loop_planner", None) if phase is not None else None


async def node_plan_evaluate(ctx: LoopRuntimeContext, state: dict[str, Any]) -> dict[str, Any]:
    """Evaluate station: inventory then assess (IG-672).

    Parent graph sees one station. Internal phases mirror the evaluate subgraph.
    Langfuse: parent ``evaluate`` span; children ``evaluate-gap`` /
    ``evaluate-gap-leg-*`` / ``evaluate-assess``.
    """
    from soothe.utils.observability.langfuse import (
        bind_planner_langfuse_trace,
        evaluate_langfuse_span_async,
        restore_planner_langfuse_trace,
    )

    await emit_plan_phase_status(ctx, label=_PLAN_EVALUATE_STATUS_LABEL)
    t0 = time.perf_counter()
    ctx.scratch.plan_gap = None
    out: dict[str, Any] = {}
    config = getattr(ctx.strange_loop, "config", None)
    planner = _loop_planner(ctx)
    prior_pin = bind_planner_langfuse_trace(planner, ctx.goal_trace)

    try:
        async with evaluate_langfuse_span_async(
            soothe_config=config,
            goal_trace=ctx.goal_trace,
            metadata={
                "iteration": ctx.loop_state.iteration,
                "thread_id": ctx.loop_state.thread_id,
            },
        ) as span:
            if should_run_inventory(ctx):
                gap = await run_inventory(ctx)
                ctx.scratch.plan_gap = gap
            else:
                ctx.scratch.plan_gap = None

            out = await node_plan_assess(ctx, state)
            route = out.get("plan_route") or out.get("assess_route") or "unknown"
            if span is not None:
                try:
                    span.update(
                        output={
                            "route": route,
                            "inventory": ctx.scratch.plan_gap is not None,
                            "gap_distance": getattr(
                                ctx.scratch.plan_gap, "distance_from_goal", None
                            ),
                        }
                    )
                except Exception:
                    logger.debug("[Plan] evaluate Langfuse span.update failed", exc_info=True)
    finally:
        restore_planner_langfuse_trace(planner, prior_pin)

    logger.info(
        "[Plan] phase=evaluate elapsed_ms=%.0f route=%s iter=%d",
        (time.perf_counter() - t0) * 1000,
        out.get("plan_route") or out.get("assess_route") or "unknown",
        ctx.loop_state.iteration,
    )
    return out


__all__ = [
    "node_plan_evaluate",
    "reduce_component_legs",
    "run_inventory",
    "seed_inventory_facets",
    "should_run_inventory",
]
