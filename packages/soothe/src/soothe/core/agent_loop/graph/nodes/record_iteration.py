"""Persist iteration, end anchor, iteration-complete events (RFC-220 ``record_iteration``)."""

from __future__ import annotations

import logging
import time
from typing import Any

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


async def node_record_iteration(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Checkpoint persist + iteration_completed emission; advance iteration counter."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state
    state_manager = ctx.state_manager
    anchor_manager = ctx.anchor_manager
    goal_record = ctx.goal_record

    plan_result = ctx.scratch.plan_result
    decision = ctx.scratch.decision
    step_results = ctx.scratch.step_results
    perf_start = ctx.scratch.iteration_perf_start or time.perf_counter()

    if plan_result is None or decision is None:
        logger.error("[record_iteration] missing plan or decision on scratch")
        await ctx.emit(
            "fatal_error",
            {"error": "Record iteration without plan/decision", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    iteration_completed = state.iteration
    state.iteration += 1
    state.total_duration_ms += int((time.perf_counter() - perf_start) * 1000)

    await state_manager.record_iteration(
        goal_record=goal_record,
        iteration=iteration_completed,
        plan_result=plan_result,
        decision=decision,
        step_results=step_results,
        state=state,
        working_memory=state.working_memory,
    )

    execution_summary = {
        "status": getattr(plan_result, "status", "success"),
        "next_action_summary": getattr(plan_result, "next_action", None),
        "tools_executed": [
            f"execute({sr.step_id})" for sr in step_results if hasattr(sr, "step_id")
        ],
        "reasoning_decision": getattr(decision, "reasoning", None),
    }

    try:
        await anchor_manager.capture_iteration_end_anchor(
            iteration=iteration_completed,
            thread_id=state.thread_id,
            checkpointer=agent_loop.core_agent.graph.checkpointer,
            execution_summary=execution_summary,
        )
    except Exception:
        logger.warning(
            "Failed to capture iteration end anchor",
            exc_info=True,
        )

    await ctx.emit(
        "iteration_completed",
        {
            "iteration": iteration_completed,
            "status": plan_result.status,
            "progress": plan_result.goal_progress,
            "next_action": plan_result.next_action,
        },
    )

    ready_after = decision.get_ready_steps(state.dependency_completion_ids())
    if ready_after:
        logger.info(
            "[→] %d step(s) remaining in current plan; next cycle will re-reason",
            len(ready_after),
        )
    state.current_decision = decision

    return {"last_outcome": "continue"}
