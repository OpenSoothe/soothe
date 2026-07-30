"""Iteration begin hooks and RFC-218 start anchors (RFC-220 ``iteration_start``)."""

from __future__ import annotations

import time
from typing import Any

from soothe.sloop.orchestrator.checkpointer import core_agent_checkpointer
from soothe.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext


async def node_iteration_start(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Emit iteration start, capture start anchor, reset per-iteration planner scratch."""
    strange_loop = ctx.strange_loop
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
        checkpointer=core_agent_checkpointer(strange_loop),
    )

    # RFC-226 fix: clear resume_synth to prevent stale flag from prior clarification
    # synthesis from affecting subsequent goals/iterations. Without this, once set,
    # every execution would skip record_iteration and loop indefinitely.
    return {"plan_route": None, "assess_route": None, "last_outcome": None, "resume_synth": None}
