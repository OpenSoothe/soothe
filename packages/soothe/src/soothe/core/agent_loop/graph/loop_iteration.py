"""Single-iteration body for the LangGraph Loop orchestrator (RFC-620, IG-394)."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Literal

from soothe.core.agent_loop.analysis.synthesis import SynthesisGenerator
from soothe.core.agent_loop.core.executor import Executor
from soothe.core.agent_loop.core.fallback_summary import generate_user_fallback_summary
from soothe.core.agent_loop.core.thread_continuation_bootstrap import (
    build_thread_continuation_bootstrap_plan,
    thread_continuation_plan_bootstrap_allowed,
)
from soothe.core.agent_loop.graph.evidence import validate_plan_evidence
from soothe.core.agent_loop.policies.goal_completion_policy import determine_completion_action
from soothe.core.agent_loop.state.schemas import (
    PlanResult,
    allocate_plan_id,
    assign_plan_step_ids,
)
from soothe.core.agent_loop.utils.reflection import _default_agent_decision
from soothe.core.agent_loop.utils.stream_normalize import (
    GoalCompletionAccumState,
    iter_messages_for_act_aggregation,
    resolve_goal_completion_text,
    update_goal_completion_from_message,
)
from soothe.utils.text_preview import preview_first

from .runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LEN = 3

IterationOutcome = Literal["continue", "completed", "fatal", "max_iterations"]


async def emit_max_iterations_terminal(ctx: LoopRuntimeContext) -> None:
    """Emit failure completion after exhausting iterations (matches legacy AgentLoop)."""
    state = ctx.loop_state
    goal_record = ctx.goal_record
    state_manager = ctx.state_manager
    checkpoint = ctx.checkpoint

    logger.warning(
        "[⚠] Max iterations (%d) reached (progress=%.0f%%)",
        state.max_iterations,
        state.previous_plan.goal_progress * 100 if state.previous_plan else 0,
    )

    if goal_record is not None:
        goal_record.status = "failed"
        goal_record.completed_at = datetime.now(UTC)
    checkpoint.status = "ready_for_next_goal"
    checkpoint.thread_health_metrics.consecutive_goal_failures += 1
    checkpoint.thread_health_metrics.last_goal_status = "failed"
    await state_manager.save(checkpoint)

    result = state.previous_plan or PlanResult(
        status="replan",
        plan_action="new",
        decision=_default_agent_decision(state.goal),
        evidence_summary=state.evidence_summary,
        goal_progress=0.0,
        confidence=0.0,
        next_action="I've hit the iteration limit; I'll pause here.",
    )
    await ctx.emit(
        "completed",
        {
            "result": result,
            "step_results_count": len(state.step_results),
        },
    )


async def run_single_iteration(ctx: LoopRuntimeContext) -> IterationOutcome:
    """Execute one Plan → Execute iteration; emit progress via ``ctx.emit``."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state
    state_manager = ctx.state_manager
    anchor_manager = ctx.anchor_manager
    goal_context_manager = ctx.goal_context_manager
    goal_record = ctx.goal_record
    checkpoint = ctx.checkpoint
    thread_continuation_mode = ctx.thread_continuation_mode
    recovery_valid_resume = ctx.recovery_valid_resume

    iteration_start = time.perf_counter()

    await ctx.emit(
        "iteration_started",
        {
            "iteration": state.iteration,
            "max_iterations": state.max_iterations,
        },
    )

    try:
        await anchor_manager.capture_iteration_start_anchor(
            iteration=state.iteration,
            thread_id=state.thread_id,
            checkpointer=agent_loop.core_agent.graph.checkpointer,
        )
    except Exception:
        logger.warning(
            "Failed to capture iteration start anchor",
            exc_info=True,
        )

    if thread_continuation_plan_bootstrap_allowed(
        thread_continuation_mode=thread_continuation_mode,
        state=state,
        recovery_valid_resume=recovery_valid_resume,
        goal_record=goal_record,
    ):
        logger.info("[Plan] iter=0 thread_continuation bootstrap (no planner LLM)")
        plan_result = build_thread_continuation_bootstrap_plan(state.goal)
    else:
        plan_result = await agent_loop.plan_phase.plan(
            goal=state.goal,
            state=state,
            context=agent_loop._build_plan_context(state),
        )

    await ctx.emit(
        "plan",
        {
            "iteration": state.iteration,
            "status": plan_result.status,
            "progress": plan_result.goal_progress,
            "confidence": plan_result.confidence,
            "next_action": plan_result.next_action,
            "assessment_reasoning": plan_result.assessment_reasoning,
            "plan_reasoning": plan_result.plan_reasoning,
            "plan_action": plan_result.plan_action,
        },
    )

    if plan_result.is_done():
        state.previous_plan = plan_result
        iteration_completed = state.iteration
        state.iteration += 1
        state.total_duration_ms += int((time.perf_counter() - iteration_start) * 1000)

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

        action, precomputed_text = determine_completion_action(
            state,
            plan_result,
            agent_loop.config.agentic.final_response,
        )

        final_output = None

        if action == "skip" or action == "direct":
            final_output = precomputed_text
            logger.info("Goal completion: action=%s chars=%d", action, len(final_output or ""))
        elif action == "synthesize":
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
        elif action == "summary":
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
            action,
        )
        skip_wire_dup = action in ("skip", "direct") and not getattr(
            state,
            "last_wave_answer_from_delegate_final",
            False,
        )
        await ctx.emit(
            "completed",
            {
                "result": updated_result,
                "step_results_count": len(state.step_results),
                "skip_goal_completion_wire_duplicate": skip_wire_dup,
            },
        )
        return "completed"

    decision = agent_loop._resolve_decision(plan_result, state)
    if decision is None:
        logger.error("[Reason] No executable decision after reason phase; aborting loop")
        await ctx.emit(
            "fatal_error",
            {"error": "Reason phase returned no executable plan", "step_id": ""},
        )
        return "fatal"

    if plan_result.plan_action == "new":
        reserved = set(state.dependency_completion_ids())
        plan_id = allocate_plan_id(decision, reserved_step_ids=reserved)
        state.plan_id = plan_id
        decision = assign_plan_step_ids(decision, plan_id=plan_id)
    elif plan_result.plan_action == "keep" and state.current_decision is None:
        reserved = set(state.dependency_completion_ids())
        plan_id = state.plan_id or allocate_plan_id(decision, reserved_step_ids=reserved)
        state.plan_id = plan_id
        decision = assign_plan_step_ids(decision, plan_id=plan_id)

    if plan_result.plan_action == "new":
        state.completed_step_ids.clear()
        state.current_decision = decision

    if not validate_plan_evidence(agent_loop.config, state, decision):
        logger.error("[Plan] Evidence validation failed for planned steps (RFC-620)")
        await ctx.emit(
            "fatal_error",
            {
                "error": "Plan steps missing valid evidence_refs for non-empty evidence ledger",
                "step_id": "",
            },
        )
        return "fatal"

    await ctx.emit(
        "plan_decision",
        {
            "iteration": state.iteration,
            "steps": [
                {"id": s.id, "description": preview_first(s.description, 80)}
                for s in decision.steps
            ],
            "execution_mode": decision.execution_mode,
        },
    )

    ready_steps = decision.get_ready_steps(state.dependency_completion_ids())
    for step in ready_steps:
        await ctx.emit(
            "step_started",
            {"step_id": step.id, "description": step.description},
        )

    step_results = []
    run_executor = Executor(
        agent_loop.core_agent,
        max_parallel_steps=agent_loop.config.execution.concurrency.max_parallel_steps,
        config=agent_loop.config,
        goal_context_manager=goal_context_manager,
    )
    async for item in run_executor.execute(
        decision=decision,
        state=state,
    ):
        if isinstance(item, tuple) and len(item) == _STREAM_CHUNK_LEN:
            await ctx.emit("stream_event", item)
        else:
            step_results.append(item)

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
        return "fatal"

    step_desc = {s.id: s.description for s in decision.steps}
    for result in step_results:
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

    state.last_wave_tool_call_count = sum(r.tool_call_count for r in step_results)
    state.last_wave_subagent_task_count = sum(r.subagent_task_completions for r in step_results)
    state.last_wave_hit_subagent_cap = any(r.hit_subagent_cap for r in step_results)

    state.previous_plan = plan_result

    iteration_completed = state.iteration
    state.iteration += 1
    state.total_duration_ms += int((time.perf_counter() - iteration_start) * 1000)

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

    return "continue"
