"""Plan-gap-analysis node (IG-557): read-only goal coverage map before plan-assess."""

from __future__ import annotations

import logging
from typing import Any

from soothe.foundation.sloop.goal_text import resolve_planning_goal

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

_PLAN_GAP_STATUS_LABEL = "Analyzing goal coverage"


async def _emit_plan_phase_status(ctx: LoopRuntimeContext, *, label: str) -> None:
    await ctx.emit("plan_phase_status", {"label": label})


async def node_plan_gap_analysis(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run structured gap analysis and stash on scratch for plan-assess."""
    strange_loop = ctx.strange_loop
    state = ctx.loop_state
    context = strange_loop._build_plan_context(state)
    await _emit_plan_phase_status(ctx, label=_PLAN_GAP_STATUS_LABEL)
    gap = await strange_loop.plan_phase.analyze_plan_gap(
        goal=resolve_planning_goal(state),
        state=state,
        context=context,
        context_engine=ctx.ce,
    )
    ctx.scratch.plan_gap = gap
    return {}
