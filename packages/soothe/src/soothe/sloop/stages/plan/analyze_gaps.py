"""Plan-gap-analysis node (IG-557): read-only goal coverage map before plan-assess."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from soothe.sloop.goal_text import resolve_planning_goal
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.stages.plan.phase_status import emit_plan_phase_status

logger = logging.getLogger(__name__)

_PLAN_GAP_STATUS_LABEL = "Analyzing coverage"
# Soft upper bound for the whole gap phase (all structured methods). Exceeding
# this skips to plan-assess without a gap map rather than stalling the TUI.
_GAP_WALL_CLOCK_SECONDS = 90.0


async def node_plan_gap_analysis(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run structured gap analysis and stash on scratch for plan-assess.

    Failures and wall-clock overruns must not abort the graph: continue to
    plan-assess without a gap map rather than ending the turn incomplete.
    """
    strange_loop = ctx.strange_loop
    state = ctx.loop_state
    context = strange_loop._build_plan_context(state)
    await emit_plan_phase_status(ctx, label=_PLAN_GAP_STATUS_LABEL)
    try:
        gap = await asyncio.wait_for(
            strange_loop.plan_phase.analyze_plan_gap(
                goal=resolve_planning_goal(state),
                state=state,
                context=context,
                context_engine=ctx.ce,
            ),
            timeout=_GAP_WALL_CLOCK_SECONDS,
        )
    except TimeoutError as exc:
        logger.warning(
            "[Plan] Gap analysis exceeded %.0fs wall clock; continuing without gap map: %s",
            _GAP_WALL_CLOCK_SECONDS,
            str(exc)[:240] or type(exc).__name__,
        )
        ctx.scratch.plan_gap = None
        return {}
    except Exception as exc:
        # StructuredOutputError, EnhancedTimeoutError, ValueError, provider blips, …
        logger.warning(
            "[Plan] Gap analysis failed; continuing without gap map: %s: %s",
            type(exc).__name__,
            str(exc)[:240],
        )
        ctx.scratch.plan_gap = None
        return {}
    ctx.scratch.plan_gap = gap
    return {}
