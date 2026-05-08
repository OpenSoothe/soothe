"""Goal completion branch (RFC-220 ``goal_completion``; RFC-219 policy)."""

from __future__ import annotations

import logging
import time
from typing import Any

from soothe.core.agent_loop.analysis.synthesis import SynthesisGenerator
from soothe.core.agent_loop.engine.fallback_summary import generate_user_fallback_summary
from soothe.core.agent_loop.planning.manager import CompletionStrategy
from soothe.core.agent_loop.state.schemas import LoopState
from soothe.core.agent_loop.utils.messages import (
    LoopAIMessage,
    LoopHumanMessage,
    last_ledger_ai_content,
)
from soothe.core.agent_loop.utils.stream_normalize import (
    GoalCompletionAccumState,
    iter_messages_for_act_aggregation,
    resolve_goal_completion_text,
    update_goal_completion_from_message,
)

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

_GOAL_COMPLETION_LEDGER_HUMAN = (
    "Goal completion: produce the final user-facing response summarizing the goal outcome."
)


def _append_goal_completion_ledger_pair(
    *,
    state: LoopState,
    iteration_completed: int,
    action: CompletionStrategy,
    final_output: str | None,
) -> None:
    """Append RFC-214 Human–AI pair for synthesized or fallback final text (not ledger-direct).

    ``LEDGER_DIRECT`` already surfaces the last execute assistant turn; duplicating it here
    would bloat the ledger and the next synthesis prompt.

    Args:
        state: Loop state whose ``loop_messages`` list is extended.
        iteration_completed: Iteration index that just finished (before ``state.iteration`` bump).
        action: Completion strategy used for this goal.
        final_output: Final user-visible text (may be empty).
    """
    text = (final_output or "").strip()
    if not text or action == CompletionStrategy.LEDGER_DIRECT:
        return
    state.loop_messages.append(
        LoopHumanMessage(
            content=_GOAL_COMPLETION_LEDGER_HUMAN,
            thread_id=state.thread_id,
            iteration=iteration_completed,
            goal_summary=(state.goal[:200] if state.goal else None),
            workspace=state.workspace,
            phase="goal_completion",
        )
    )
    state.loop_messages.append(
        LoopAIMessage(
            content=text,
            thread_id=state.thread_id,
            iteration=iteration_completed,
            phase="goal_completion",
        )
    )


async def node_goal_completion(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Finalize goal when planner reports ``done`` (record iteration, synthesis, emit completed).

    IG-XXX: Clear all pending execution state to prevent task leakage into next query.
    When goal completion happens, any pending decision, step_results, or working memory
    from this query must be cleared so the next query starts fresh.
    """
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

    # IG-XXX: Clear pending execution state to prevent task leakage
    # When this goal completes, all pending tasks/decisions must be cancelled silently.
    # The next query should start with a clean slate.
    state.step_results = []  # Clear completed step results
    state.current_decision = None  # Clear pending decision for next iteration
    ctx.scratch.decision = None  # Clear scratch decision
    ctx.scratch.step_results = []  # Clear scratch step results
    ctx.scratch.plan_result = None  # Clear scratch plan result (already saved)
    ctx.scratch.plan_assessment = None  # Clear assessment
    logger.debug(
        "[goal_completion] Cleared pending state: step_results=%d, decision=%s",
        len(state.step_results),
        "cleared" if state.current_decision is None else "present",
    )

    await state_manager.record_iteration(
        goal_record=goal_record,
        iteration=iteration_completed,
        plan_result=plan_result,
        decision=None,  # IG-XXX: Explicitly None - no pending decision
        step_results=[],  # IG-XXX: Empty - no pending steps
        state=state,
        working_memory=state.working_memory,
    )

    synthesis_gen = SynthesisGenerator(
        agent_loop.loop_planner._model, agent_loop.core_agent, agent_loop.config
    )

    action = plan_manager.determine_completion_strategy(
        state,
        plan_result,
        agent_loop.config.agent_loop.final_response,
    )

    final_output = None
    used_synthesis_fallback = False

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
            used_synthesis_fallback = True
            final_output = generate_user_fallback_summary(state, plan_result)
    elif action == CompletionStrategy.SUMMARY:
        final_output = generate_user_fallback_summary(state, plan_result)
        logger.info("Goal completion: action=summary chars=%d", len(final_output or ""))

    _append_goal_completion_ledger_pair(
        state=state,
        iteration_completed=iteration_completed,
        action=action,
        final_output=final_output,
    )

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
            "step_results_count": len(state.step_results),
            "skip_goal_completion_wire_duplicate": skip_goal_completion_wire_duplicate,
        },
    )
    out: dict[str, Any] = {"last_outcome": "completed"}
    return out
