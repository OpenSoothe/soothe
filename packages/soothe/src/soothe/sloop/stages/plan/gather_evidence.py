"""Bounded evidence gathering phase (RFC-220 ``bounded_evidence_gather``).

Placeholder: ledger-driven bounded tool rounds land in IG-394 / future work. Topology edge is
wired so validation and repair loops can attach without reshaping the outer graph.

IG-476: Detects fresh-loop conditions and shortcuts evaluate by setting a synthetic
StatusAssessment and routing directly to plan_generate.

IG-671: Structural keep reuses a healthy in-flight plan without evaluate/generate.

IG-672: Non-shortcut paths route to the ``evaluate`` station (inventory + assess).
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
from soothe.sloop.orchestrator.continuation_routing import (
    fresh_loop_bypass_assessment,
    is_fresh_loop_skip_evaluate,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


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


async def node_bounded_evidence_gather(
    ctx: LoopRuntimeContext, _state: dict[str, Any]
) -> dict[str, Any]:
    """Detect fresh-loop / structural-keep shortcuts before evaluate (IG-476, IG-671).

    Fresh complex skips evaluate. Mid-loop always continues to evaluate (IG-676).
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

    if is_fresh_loop_skip_evaluate(ctx):
        logger.info("[EvidenceGather] Fresh-loop detected, skipping evaluate")
        ctx.scratch.plan_assessment = fresh_loop_bypass_assessment()
        return {"evidence_gather_route": "plan_generate_skip_evaluate"}
    return {"evidence_gather_route": "evaluate"}
