"""Execute planned steps via CoreAgent (RFC-220 ``execute``)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from soothe.core.events.constants import AGENT_LOOP_CONTEXT_COMPACTED
from soothe.core.loop.engine.context_window_manager import ContextWindowManager
from soothe.core.loop.engine.executor import Executor, StepWaveQueued, StepWaveStart
from soothe.core.loop.state.schemas import StepAction, StepResult

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

    started_step_ids: set[str] = set()
    queued_step_ids: set[str] = set()

    async def _emit_step_queued_for_steps(steps: list[StepAction]) -> None:
        """Emit ``step_queued`` for ready steps waiting on ``max_parallel_steps``."""
        for step in steps:
            if step.id in queued_step_ids or step.id in started_step_ids:
                continue
            queued_step_ids.add(step.id)
            await ctx.emit(
                "step_queued",
                {"step_id": step.id, "description": step.description},
            )

    async def _emit_step_started_for_steps(steps: list[StepAction]) -> None:
        """Emit ``step_started`` when a step enters an active execute batch (live TUI)."""
        for step in steps:
            if step.id in started_step_ids:
                continue
            started_step_ids.add(step.id)
            queued_step_ids.discard(step.id)
            await ctx.emit(
                "step_started",
                {"step_id": step.id, "description": step.description},
            )

    step_results: list[StepResult] = []
    step_desc = {s.id: s.description for s in decision.steps}

    # RFC-223: Pass checkpointer for thread fork inheritance
    checkpointer = getattr(agent_loop.core_agent.graph, "checkpointer", None)

    run_executor = Executor(
        agent_loop.core_agent,
        checkpointer=checkpointer,
        max_parallel_steps=agent_loop.config.agent.loop.limits.max_parallel_steps,
        config=agent_loop.config,
        goal_context_manager=goal_context_manager,
        loop_id=ctx.state_manager.loop_id,
    )
    async for item in run_executor.execute(
        decision=decision,
        state=state,
    ):
        if isinstance(item, StepWaveQueued):
            await _emit_step_queued_for_steps(list(item.steps))
        elif isinstance(item, StepWaveStart):
            await _emit_step_started_for_steps(list(item.steps))
        elif isinstance(item, tuple) and len(item) == _STREAM_CHUNK_LEN:
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
        checkpoint.status = "idle"
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
    state.last_wave_hit_tool_budget = any(r.hit_tool_budget for r in step_results)

    state.previous_plan = plan_result

    ctx.scratch.step_results = step_results

    # RFC-224: Check context window and compact if needed
    if checkpointer is not None and agent_loop.config is not None:
        try:
            context_manager = ContextWindowManager(checkpointer, agent_loop.config)
            compaction_result = await context_manager.check_and_compact_if_needed(
                state.thread_id,
                state,
            )
            if compaction_result is not None:
                await ctx.emit(
                    AGENT_LOOP_CONTEXT_COMPACTED,
                    {
                        "thread_id": compaction_result.thread_id,
                        "tokens_before": compaction_result.tokens_before,
                        "tokens_after": compaction_result.tokens_after,
                        "messages_removed": compaction_result.messages_removed,
                        "summary_preview": compaction_result.summary_preview,
                    },
                )
        except Exception:
            logger.warning(
                "[execute] Context compaction check failed for thread %s",
                state.thread_id,
                exc_info=True,
            )

    return {}
