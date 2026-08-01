"""Bounded evidence gathering phase (RFC-220 ``bounded_evidence_gather``).

Placeholder: ledger-driven bounded tool rounds land in IG-394 / future work. Topology edge is
wired so validation and repair loops can attach without reshaping the outer graph.

IG-476: Detects fresh-loop conditions and shortcuts plan_assess by setting a synthetic
StatusAssessment and routing directly to plan_generate.

IG-671: Structural keep reuses a healthy in-flight plan without gap/assess/generate.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.cognition.structural_keep import (
    build_keep_plan_result,
    note_structural_keep,
    reset_structural_keep_streak,
    structural_keep_block_reason,
)
from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.prompts.plan_ledger_projection import (
    _current_goal_has_execute_ledger,
    resolve_planner_projection_mode,
)
from soothe.sloop.state.schemas import StatusAssessment

logger = logging.getLogger(__name__)


def _is_fresh_loop(ctx: LoopRuntimeContext) -> bool:
    """Detect fresh-loop conditions where plan_assess can be skipped (IG-476).

    RFC-624 Phase 4 Stage 2: Uses CE query instead of checkpoint.goal_history.

    A loop is "fresh" when ALL of:
    - state.iteration == 0
    - not state.step_results (no prior execution)
    - not ctx.continue_loop_mode (not a continuation)
    - CE has no completed goals (no prior goal context)
    - No recovery state requiring assessment
    """
    state = ctx.loop_state
    if state.iteration != 0:
        return False
    if state.step_results:
        return False
    if ctx.continue_loop_mode:
        return False
    # RFC-624 Phase 4: CE is guaranteed active when graph nodes execute.
    # Check CE DAG for completed goals instead of checkpoint.goal_history.
    if ctx.ce is None:
        # No CE should not happen in production; tests must provide CE backend.
        return False
    has_completed_goals = any(g.status == "completed" for g in ctx.ce.get_all_goals())
    if has_completed_goals:
        return False
    # Recovery paths may need assessment
    if ctx.recovery_valid_resume:
        return False
    return True


def _create_fresh_loop_assessment() -> StatusAssessment:
    """Create synthetic StatusAssessment for fresh-loop bypass (IG-476)."""
    return StatusAssessment(
        status="continue",
        goal_progress="none",
        assessment_reasoning="Fresh-loop bypass: no prior execution to assess.",
        require_goal_completion=False,
    )


def _gap_analysis_enabled(ctx: LoopRuntimeContext) -> bool:
    strange_loop = ctx.strange_loop
    if strange_loop.config is None:
        return True
    return bool(strange_loop.config.agent.loop.plan_gap_analysis_enabled)


def _structural_keep_config(ctx: LoopRuntimeContext) -> tuple[bool, int]:
    cfg = getattr(ctx.strange_loop, "config", None)
    if cfg is None:
        return True, 3
    loop = cfg.agent.loop
    return bool(loop.plan_structural_keep_enabled), int(loop.plan_structural_keep_max_streak)


def _try_structural_keep(ctx: LoopRuntimeContext) -> dict[str, Any] | None:
    """Reuse in-flight plan when structural gates pass (IG-671)."""
    enabled, max_streak = _structural_keep_config(ctx)
    state = ctx.loop_state
    block = structural_keep_block_reason(state, enabled=enabled, max_streak=max_streak)
    if block is not None:
        logger.debug("[EvidenceGather] structural keep blocked (%s)", block)
        return None

    strange_loop = ctx.strange_loop
    context = strange_loop._build_plan_context(state)
    plan_result = build_keep_plan_result(state)
    plan_result = strange_loop.plan_phase.finalize_plan_result(
        state=state,
        context=context,
        result=plan_result,
    )
    note_structural_keep(state)
    ctx.scratch.plan_result = plan_result
    ctx.scratch.plan_assessment = None
    ctx.scratch.plan_gap = None
    return {"evidence_gather_route": "keep_plan", "plan_route": "execute"}


def _should_run_gap_analysis(ctx: LoopRuntimeContext) -> bool:
    state = ctx.loop_state
    if not _gap_analysis_enabled(ctx):
        return False
    intake = getattr(state.intent, "intake_label", None) if state.intent is not None else None
    if intake == IntakeLabel.TRIVIAL:
        return False
    mode = resolve_planner_projection_mode(state)
    if (
        mode == "new_goal"
        and not state.step_results
        and not _current_goal_has_execute_ledger(state)
    ):
        logger.info("[Plan] gap analysis skipped (reason=iter0_no_execution)")
        return False
    # IG-671: mid-loop simple intake is assess-only (gap adds little vs cost).
    cfg = getattr(ctx.strange_loop, "config", None)
    skip_simple = True if cfg is None else bool(cfg.agent.loop.plan_gap_skip_simple_mid_loop)
    if skip_simple and intake == IntakeLabel.SIMPLE and mode == "mid_goal":
        logger.info("[Plan] gap analysis skipped (reason=simple_mid_loop)")
        return False
    return True


async def node_bounded_evidence_gather(
    ctx: LoopRuntimeContext, _state: dict[str, Any]
) -> dict[str, Any]:
    """Detect fresh-loop / structural-keep shortcuts before gap/assess (IG-476, IG-671).

    For fresh loops (no prior execution, iter=0, not continuation), sets a synthetic
    StatusAssessment and routes directly to plan_generate, saving assess latency.
    """
    keep_route = _try_structural_keep(ctx)
    if keep_route is not None:
        plan_result = ctx.scratch.plan_result
        state = ctx.loop_state
        if plan_result is not None:
            await ctx.emit(
                "plan",
                {
                    "iteration": state.iteration,
                    "status": plan_result.status,
                    "progress": plan_result.goal_progress,
                    "next_action": plan_result.next_action,
                    "plan_action": plan_result.plan_action,
                },
            )
        return keep_route

    reset_structural_keep_streak(ctx.loop_state)

    if _is_fresh_loop(ctx):
        logger.info("[EvidenceGather] Fresh-loop detected, skipping plan_assess")
        ctx.scratch.plan_assessment = _create_fresh_loop_assessment()
        return {"evidence_gather_route": "plan_generate_skip_assess"}
    if _should_run_gap_analysis(ctx):
        return {"evidence_gather_route": "analyze_gaps"}
    return {"evidence_gather_route": "assess"}
