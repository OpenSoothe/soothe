"""Iteration begin hooks and RFC-218 start anchors (RFC-220 ``iteration_start``)."""

from __future__ import annotations

import logging
import time
from typing import Any

from ..phase_scratch import LoopPhaseScratch
from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


async def node_iteration_start(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Emit iteration start, capture start anchor, reset per-iteration planner scratch."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state

    ctx.scratch = LoopPhaseScratch(iteration_perf_start=time.perf_counter())

    await ctx.emit(
        "iteration_started",
        {
            "iteration": state.iteration,
            "max_iterations": state.max_iterations,
        },
    )

    try:
        await ctx.anchor_manager.capture_iteration_start_anchor(
            iteration=state.iteration,
            thread_id=state.thread_id,
            checkpointer=agent_loop.core_agent.graph.checkpointer,
        )
    except Exception:
        logger.warning(
            "Failed to capture iteration start anchor",
            exc_info=True,
        )

    return {"plan_route": None, "last_outcome": None}
