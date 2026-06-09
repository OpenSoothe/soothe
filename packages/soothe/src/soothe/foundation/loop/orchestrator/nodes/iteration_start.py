"""Iteration begin hooks and RFC-218 start anchors (RFC-220 ``iteration_start``)."""

from __future__ import annotations

import time
from typing import Any

from ..checkpointer import core_agent_checkpointer
from ..phase_scratch import LoopPhaseScratch
from ..runtime_context import LoopRuntimeContext


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

    await ctx.anchor_manager.capture_iteration_start_anchor(
        iteration=state.iteration,
        thread_id=state.thread_id,
        checkpointer=core_agent_checkpointer(agent_loop),
    )

    return {"plan_route": None, "assess_route": None, "last_outcome": None}
