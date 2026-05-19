"""Execute planned steps via CoreAgent (RFC-220 ``execute``)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from soothe.core.loop.engine.executor import Executor
from soothe.core.loop.state.schemas import StepResult

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LEN = 3


async def _record_and_emit_step_completed(
    ctx: LoopRuntimeContext,
    *,
    result: StepResult,
    step_desc: dict[str, str],
) -> None:
    """Apply step outcome to loop state and emit ``step_completed`` for live UIs."""
    state = ctx.loop_state
    state.add_step_result(result)
    if state.working_memory is not None:
        outcome_summary = result.to_evidence_string(truncate=True)
        state.working_memory.record_step_result(
            step_id=result.step_id,
            description=step_desc.get(result.step_id, ""),
            output=outcome_summary,
            error=result.error,
            success=result.success,
            workspace=state.workspace,
            thread_id=state.thread_id,
        )
    if result.success:
        output_preview = "Done"
        if result.tool_call_count > 0:
            output_preview = f"Done [{result.tool_call_count} tools]"
    else:
        output_preview = f"Failed: {result.error[:50]}" if result.error else "Failed"

    await ctx.emit(
        "step_completed",
        {
            "step_id": result.step_id,
            "success": result.success,
            "output_preview": output_preview,
            "error": result.error or None,
            "duration_ms": result.duration_ms,
            "tool_call_count": result.tool_call_count,
        },
    )


async def node_execute(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run ready steps, stream events, apply step results to ``LoopState``."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state
    state_manager = ctx.state_manager
    goal_context_manager = ctx.goal_context_manager
    goal_record = ctx.goal_record
    checkpoint = ctx.checkpoint
    decision = ctx.scratch.decision
    plan_result = ctx.scratch.plan_result

    if decision is None or plan_result is None:
        logger.error("[execute] missing decision or plan_result on scratch")
        await ctx.emit(
            "fatal_error",
            {"error": "Execute without decision", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    ready_steps = decision.get_ready_steps(state.dependency_completion_ids())
    for step in ready_steps:
        await ctx.emit(
            "step_started",
            {"step_id": step.id, "description": step.description},
        )

    step_results: list[StepResult] = []
    step_desc = {s.id: s.description for s in decision.steps}
    run_executor = Executor(
        agent_loop.core_agent,
        max_parallel_steps=agent_loop.config.agent_loop.limits.max_parallel_steps,
        config=agent_loop.config,
        goal_context_manager=goal_context_manager,
        loop_id=ctx.state_manager.loop_id,
    )
    async for item in run_executor.execute(
        decision=decision,
        state=state,
    ):
        if isinstance(item, tuple) and len(item) == _STREAM_CHUNK_LEN:
            await ctx.emit("stream_event", item)
        elif isinstance(item, StepResult):
            step_results.append(item)
            await _record_and_emit_step_completed(
                ctx,
                result=item,
                step_desc=step_desc,
            )

    fatal_errors = [r for r in step_results if r.error_type == "fatal"]
    if fatal_errors:
        logger.error(
            "Fatal error detected, aborting loop: %s",
            fatal_errors[0].error,
        )
        if goal_record is not None:
            goal_record.status = "failed"
            goal_record.completed_at = datetime.now(UTC)
        checkpoint.status = "ready_for_next_goal"
        checkpoint.thread_health_metrics.consecutive_goal_failures += 1
        checkpoint.thread_health_metrics.last_goal_status = "failed"
        await state_manager.save(checkpoint)
        await ctx.emit(
            "fatal_error",
            {
                "error": fatal_errors[0].error,
                "step_id": fatal_errors[0].step_id,
            },
        )
        return {"last_outcome": "fatal"}

    state.last_wave_tool_call_count = sum(r.tool_call_count for r in step_results)
    state.last_wave_subagent_task_count = sum(r.subagent_task_completions for r in step_results)
    state.last_wave_hit_subagent_cap = any(r.hit_subagent_cap for r in step_results)

    state.previous_plan = plan_result

    ctx.scratch.step_results = step_results

    return {}
