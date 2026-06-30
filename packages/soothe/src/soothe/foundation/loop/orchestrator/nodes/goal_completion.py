"""Goal completion branch (RFC-220 ``goal_completion``; RFC-219 policy)."""

from __future__ import annotations

import gc
import logging
import time
from typing import Any

from soothe.foundation.context.planning.models import CompletionStrategy
from soothe.foundation.loop.engine.synthesis import (
    SynthesisGenerator,
    generate_user_fallback_summary,
)
from soothe.foundation.loop.state.schemas import LoopState
from soothe.foundation.loop.utils.messages import (
    LoopAIMessage,
    LoopHumanMessage,
    last_ledger_ai_content,
)
from soothe.foundation.loop.utils.stream_normalize import (
    GoalCompletionAccumState,
    iter_messages_for_act_aggregation,
    resolve_goal_completion_text,
    update_goal_completion_from_message,
)

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

_GOAL_COMPLETION_LEDGER_HUMAN = (
    "Produce the final user-facing response summarizing the outcome. "
    "Use the same primary natural language as the user's request; keep code, paths, and quoted literals unchanged."
)


def _append_goal_completion_ledger_pair(
    *,
    state: LoopState,
    iteration_completed: int,
    action: CompletionStrategy,
    final_output: str | None,
    context_engine: Any | None = None,
) -> None:
    """Append RFC-214 Human–AI pair for synthesized or fallback final text (not ledger-direct).

    ``LEDGER_DIRECT`` already surfaces the last execute assistant turn; duplicating it here
    would bloat the ledger and the next synthesis prompt.

    Args:
        state: Loop state whose ``loop_messages`` list is extended.
        iteration_completed: Iteration index that just finished (before ``state.iteration`` bump).
        action: Completion strategy used for this goal.
        final_output: Final user-visible text (may be empty).
        context_engine: ContextEngine instance for direct LedgerManager writes.
    """
    from soothe.foundation.loop.utils.messages import _record_ledger_message

    text = (final_output or "").strip()
    if not text or action == CompletionStrategy.LEDGER_DIRECT:
        return
    human_msg = LoopHumanMessage(
        content=_GOAL_COMPLETION_LEDGER_HUMAN,
        thread_id=state.thread_id,
        iteration=iteration_completed,
        goal_summary=(state.goal[:200] if state.goal else None),
        workspace=state.workspace,
        phase="goal_completion",
    )
    ai_msg = LoopAIMessage(
        content=text,
        thread_id=state.thread_id,
        iteration=iteration_completed,
        phase="goal_completion",
    )
    _record_ledger_message(context_engine, human_msg, "goal_completion")
    _record_ledger_message(context_engine, ai_msg, "goal_completion")


async def node_goal_completion(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Finalize goal when planner reports ``done`` (record iteration, synthesis, emit completed).

    IG-475: Clear all pending execution state to prevent task leakage into next query.
    When goal completion happens, any pending decision, step_results, or working memory
    from this query must be cleared so the next query starts fresh.
    """
    strange_loop = ctx.strange_loop
    strange_loop = strange_loop  # Legacy alias
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

    # RFC-624 Phase 4 Stage 2: No longer snapshot/restore step_results.
    # When CE is bound, state.step_results property reads from CE DAG,
    # which retains step data after finalize_goal(). Clear caches only.
    # When CE is not bound (tests), synthesis reads from cache directly.
    pre_clear_step_results = list(state.step_results)  # for metrics logging only

    state.clear_goal_state()
    ctx.scratch.decision = None
    ctx.scratch.step_results = []
    ctx.scratch.plan_result = None
    ctx.scratch.plan_assessment = None
    logger.debug(
        "[goal_completion] Cleared goal state for next query (iteration=%d)",
        iteration_completed,
    )

    await state_manager.record_iteration(
        goal_record=goal_record,
        iteration=iteration_completed,
        plan_result=plan_result,
        decision=None,  # IG-475: Explicitly None - no pending decision
        step_results=[],  # IG-475: Empty - no pending steps (state cleared)
        state=state,
        working_memory=None,  # IG-475: Working memory cleared
    )

    synthesis_gen = SynthesisGenerator(
        strange_loop.loop_planner._model,
        strange_loop.core_agent,
        strange_loop.config,
        loop_id=ctx.state_manager.loop_id,
        fast_llm_client=strange_loop._fast_llm,
    )

    action = plan_manager.determine_completion_strategy(
        state,
        plan_result,
        strange_loop.config.agent.loop.final_response,
    )

    # RFC-624 Phase 4: Finalize goal lifecycle + persist CE state
    if ctx.ce is not None:
        try:
            await ctx.ce.finalize_goal(ctx.ce_goal_id, status="completed")
            await ctx.ce.save()
        except Exception:
            logger.warning("[goal_completion] CE goal finalization failed", exc_info=True)

    # Build the completion DAG report after CE finalization so goal status reflects
    # terminal state instead of the pre-finalization "active" snapshot.
    dag_report = plan_manager.format_completion_dag_report().strip()
    if dag_report:
        logger.info(
            "[goal_completion] Planning DAG at goal end (action=%s thread_id=%s):\n%s",
            action.value,
            state.thread_id,
            dag_report,
        )
    else:
        logger.debug(
            "[goal_completion] No unified plan DAG nodes to log (action=%s thread_id=%s)",
            action.value,
            state.thread_id,
        )

    final_output = None
    used_synthesis_fallback = False

    if action == CompletionStrategy.LEDGER_DIRECT:
        final_output = last_ledger_ai_content(state)
        logger.info("Goal completion: action=ledger_direct chars=%d", len(final_output or ""))
    elif action == CompletionStrategy.SYNTHESIZE:
        # RFC-624 Phase 4 Stage 2: No restore needed.
        # state.step_results property reads from CE DAG when bound.
        # Synthesis projection reads state.step_results which queries CE.
        logger.info("Goal completion: action=synthesis starting stream")
        accum = GoalCompletionAccumState()
        chunk_count = 0

        async for inner in synthesis_gen.generate_synthesis(state.goal, state):
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
            used_synthesis_fallback = True
            final_output = generate_user_fallback_summary(state, plan_result)
    elif action == CompletionStrategy.SUMMARY:
        # RFC-624 Phase 4 Stage 2: No restore needed.
        # state.step_results property reads from CE DAG when bound.
        final_output = generate_user_fallback_summary(state, plan_result)
        logger.info("Goal completion: action=summary chars=%d", len(final_output or ""))

    _append_goal_completion_ledger_pair(
        state=state,
        iteration_completed=iteration_completed,
        action=action,
        final_output=final_output,
        context_engine=ctx.ce,
    )

    # Goal_completion only runs when the goal is, in fact, done. Force status="done"
    # so the runner emits the final answer to the wire (RFC-225/RFC-226: the bootstrap
    # path arrives here with PlanResult.status="continue", which would otherwise
    # suppress loop_assistant_messages_chunk emission).
    updated_result = plan_result.model_copy(
        update={
            "full_output": final_output,
            "status": "done",
        }
    )

    await state_manager.finalize_goal(goal_record, updated_result.full_output, loop_state=state)
    logger.info(
        "Goal completed: iterations=%d duration=%dms action=%s",
        state.iteration,
        state.total_duration_ms,
        action.value,
    )
    # Runner ``loop_assistant_messages_chunk`` replay: skip when synthesis already
    # streamed ``phase=goal_completion`` on ``messages`` (``stream_event``). Do not
    # skip for ``ledger_direct`` — headless CLI suppresses execute-phase prose (IG-343)
    # and relies on this replay for the user-visible answer (RFC-614 / RFC-500).
    skip_goal_completion_wire_duplicate = (
        action == CompletionStrategy.SYNTHESIZE and not used_synthesis_fallback
    )
    await ctx.emit(
        "completed",
        {
            "result": updated_result,
            "step_results_count": len(pre_clear_step_results),
            "skip_goal_completion_wire_duplicate": skip_goal_completion_wire_duplicate,
        },
    )
    # IG-475: Force garbage collection after goal completion to reclaim
    # LLM streaming objects (langchain message buffers, tokenizer caches, etc.)
    # This prevents accumulation of ephemeral objects across multiple queries.
    gc.collect()
    out: dict[str, Any] = {"last_outcome": "completed"}
    return out
