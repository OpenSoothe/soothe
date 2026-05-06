"""Goal completion branch (RFC-220 ``goal_completion``; RFC-219 policy)."""

from __future__ import annotations

import logging
import time
from typing import Any

from soothe.core.agent_loop.analysis.synthesis import SynthesisGenerator
from soothe.core.agent_loop.core.fallback_summary import generate_user_fallback_summary
from soothe.core.agent_loop.core.plan_manager import CompletionStrategy
from soothe.core.agent_loop.utils.messages import last_ledger_ai_content
from soothe.core.agent_loop.utils.stream_normalize import (
    GoalCompletionAccumState,
    iter_messages_for_act_aggregation,
    resolve_goal_completion_text,
    update_goal_completion_from_message,
)

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


async def node_goal_completion(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Finalize goal when planner reports ``done`` (record iteration, synthesis, emit completed)."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state
    state_manager = ctx.state_manager
    goal_record = ctx.goal_record
    plan_manager = ctx.plan_manager

    plan_result = ctx.scratch.plan_result
    if plan_result is None:
        logger.error("[goal_completion] missing scratch.plan_result")
        await ctx.emit(
            "fatal_error",
            {"error": "Goal completion reached without plan result", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    perf_start = ctx.scratch.iteration_perf_start or time.perf_counter()

    state.previous_plan = plan_result
    iteration_completed = state.iteration
    state.iteration += 1
    state.total_duration_ms += int((time.perf_counter() - perf_start) * 1000)

    await state_manager.record_iteration(
        goal_record=goal_record,
        iteration=iteration_completed,
        plan_result=plan_result,
        decision=None,
        step_results=[],
        state=state,
        working_memory=state.working_memory,
    )

    synthesis_gen = SynthesisGenerator(
        agent_loop.loop_planner._model, agent_loop.core_agent, agent_loop.config
    )

    action = plan_manager.determine_completion_strategy(
        state,
        plan_result,
        agent_loop.config.agentic.final_response,
    )

    final_output = None

    if action == CompletionStrategy.LEDGER_DIRECT:
        final_output = last_ledger_ai_content(state)
        logger.info("Goal completion: action=ledger_direct chars=%d", len(final_output or ""))
    elif action == CompletionStrategy.SYNTHESIZE:
        logger.info("Goal completion: action=synthesis starting stream")
        accum = GoalCompletionAccumState()
        chunk_count = 0

        async for inner in synthesis_gen.generate_synthesis(state.goal, state, plan_result):
            chunk_count += 1
            for msg in iter_messages_for_act_aggregation(inner):
                update_goal_completion_from_message(accum, msg)
            await ctx.emit("stream_event", inner)

        final_output = resolve_goal_completion_text(accum)

        logger.info(
            "Synthesis stream: chunks=%d ai_msgs=%d chars=%d",
            chunk_count,
            accum.ai_msg_count,
            len(final_output or ""),
        )

        if not final_output:
            logger.warning("No synthesis text from CoreAgent, using fallback")
            final_output = generate_user_fallback_summary(state, plan_result)
    elif action == CompletionStrategy.SUMMARY:
        final_output = generate_user_fallback_summary(state, plan_result)
        logger.info("Goal completion: action=summary chars=%d", len(final_output or ""))

    updated_result = plan_result.model_copy(
        update={
            "full_output": final_output,
        }
    )

    await state_manager.finalize_goal(goal_record, updated_result.full_output)
    logger.info(
        "Goal completed: iterations=%d duration=%dms action=%s",
        state.iteration,
        state.total_duration_ms,
        action.value,
    )
    await ctx.emit(
        "completed",
        {
            "result": updated_result,
            "step_results_count": len(state.step_results),
        },
    )
    out: dict[str, Any] = {"last_outcome": "completed"}
    return out
