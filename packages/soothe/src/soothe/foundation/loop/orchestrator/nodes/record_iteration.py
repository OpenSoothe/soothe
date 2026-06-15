"""Persist iteration, end anchor, iteration-complete events (RFC-220 ``record_iteration``)."""

from __future__ import annotations

import logging
import time
from typing import Any

from ..checkpointer import core_agent_checkpointer
from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


async def node_record_iteration(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Checkpoint persist + iteration_completed emission; advance iteration counter."""
    strange_loop = ctx.strange_loop
    strange_loop = strange_loop  # Legacy alias
    state = ctx.loop_state
    state_manager = ctx.state_manager
    anchor_manager = ctx.anchor_manager
    goal_record = ctx.goal_record
    plan_manager = ctx.plan_manager

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

    # Record step outcomes in the plan DAG
    plan_manager.record_step_outcomes(step_results)

    # RFC-624 Phase 4: async step feedback + CE persistence
    if ctx.ce is not None:
        try:
            from soothe.context.models import StepExecution

            for r in step_results:
                execution = StepExecution(
                    duration_ms=r.duration_ms,
                    thread_id=r.thread_id,
                    error=r.error,
                    error_type=r.error_type,
                    outcome=r.outcome if r.outcome else None,
                    tool_call_count=r.tool_call_count,
                    subagent_task_completions=r.subagent_task_completions,
                    hit_subagent_cap=r.hit_subagent_cap,
                    hit_tool_budget=r.hit_tool_budget,
                )
                if r.success:
                    await ctx.ce.complete_step(ctx.ce_goal_id, r.step_id, execution)
                else:
                    await ctx.ce.fail_step(ctx.ce_goal_id, r.step_id, execution)
            await ctx.ce.save()
        except Exception:
            logger.warning("[record_iteration] CE step feedback failed", exc_info=True)

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

    await anchor_manager.capture_iteration_end_anchor(
        iteration=iteration_completed,
        thread_id=state.thread_id,
        checkpointer=core_agent_checkpointer(strange_loop),
        execution_summary=execution_summary,
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

    # RFC-624 Phase 4 Step 5: record action + previous_plan on CE goal
    if ctx.ce is not None and ctx.ce_goal_id:
        try:
            if plan_result.next_action:
                ctx.ce.record_action(ctx.ce_goal_id, plan_result.next_action)
            ctx.ce.set_previous_plan(ctx.ce_goal_id, plan_result)
        except Exception:
            logger.debug(
                "[record_iteration] CE record_action/set_previous_plan failed", exc_info=True
            )

    # RFC-226: terminal bootstrap fast-exit — when the plan asserts that its single
    # step IS the goal completion (continuation bootstrap path), route straight to
    # goal_completion and skip the iter=1 plan_assess status check.
    terminal = bool(getattr(plan_result, "terminal_after_execute", False))

    # Both "continue" and "replan" status cycle back to iteration_gate for next iteration
    # The iteration_gate will check iteration limit and route accordingly
    return {
        "last_outcome": "continue",
        "after_record_route": "goal_completion" if terminal else "",
    }
