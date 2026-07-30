"""Plan-gap-analysis node (IG-557): read-only goal coverage map before plan-assess."""

from __future__ import annotations

import logging
from typing import Any

from soothe_nano.utils.llm.structured import StructuredOutputError

from soothe.sloop.goal_text import resolve_planning_goal
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

_PLAN_GAP_STATUS_LABEL = "Analyzing coverage"


async def _emit_plan_phase_status(ctx: LoopRuntimeContext, *, label: str) -> None:
    await ctx.emit(
        "plan_phase_status",
        {
            "label": label,
            "total_tokens_used": ctx.loop_state.total_tokens_used,
        },
    )


async def node_plan_gap_analysis(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run structured gap analysis and stash on scratch for plan-assess.

    Structured-output failures must not abort the graph (IG-593): continue to
    plan-assess without a gap map rather than ending the turn incomplete.
    """
    strange_loop = ctx.strange_loop
    state = ctx.loop_state
    context = strange_loop._build_plan_context(state)
    await _emit_plan_phase_status(ctx, label=_PLAN_GAP_STATUS_LABEL)
    try:
        gap = await strange_loop.plan_phase.analyze_plan_gap(
            goal=resolve_planning_goal(state),
            state=state,
            context=context,
            context_engine=ctx.ce,
        )
    except StructuredOutputError as exc:
        logger.warning(
            "[Plan] Gap analysis structured output failed; continuing without gap map: %s",
            str(exc)[:240],
        )
        ctx.scratch.plan_gap = None
        return {}
    ctx.scratch.plan_gap = gap
    return {}
