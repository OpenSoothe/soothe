"""Goal completion branch (RFC-220 ``goal_completion``; RFC-219 policy)."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import logging
import time
from typing import Any

from soothe.foundation.context.planning.models import CompletionStrategy
from soothe.foundation.sloop.engine.goal_completion_output import (
    reconcile_synthesis_with_step_ledger,
)
from soothe.foundation.sloop.engine.synthesis import (
    SynthesisGenerator,
    generate_user_fallback_summary,
)
from soothe.foundation.sloop.state.schemas import LoopState
from soothe.foundation.sloop.utils.messages import (
    LoopAIMessage,
    LoopHumanMessage,
    last_ledger_ai_content,
)
from soothe.foundation.sloop.utils.stream_normalize import iter_messages_for_act_aggregation
from soothe.utils.goal_completion_stream import (
    GoalCompletionAccumState,
    resolve_goal_completion_text,
    update_goal_completion_from_message,
)

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

_GOAL_FINALIZE_STATUS_LABEL = "Finalizing goal"

_GOAL_COMPLETION_LEDGER_HUMAN_BASE = (
    "Produce the final user-facing response summarizing the outcome. "
    "Keep code, paths, and quoted literals unchanged."
)


def _goal_completion_ledger_human_content(state: LoopState) -> str:
    """Human ledger line for goal completion: user submission for trivial, else synthesis prompt."""
    from soothe.foundation.sloop.intention.models import (
        IntakeLabel,
        ResponseLanguage,
        normalize_response_language,
    )

    intent = getattr(state, "intent", None)
    intake_label = getattr(intent, "intake_label", None) if intent is not None else None
    if intake_label == IntakeLabel.TRIVIAL:
        submission = (getattr(state, "goal_user_submission", None) or state.goal or "").strip()
        if submission:
            return submission
    language = normalize_response_language(getattr(state, "response_language", None))
    if language is None or language == ResponseLanguage.OTHER:
        return (
            _GOAL_COMPLETION_LEDGER_HUMAN_BASE
            + " Use the same primary natural language as the user's request."
        )
    display = {
        ResponseLanguage.EN: "English",
        ResponseLanguage.ZH: "Chinese",
        ResponseLanguage.JA: "Japanese",
        ResponseLanguage.KO: "Korean",
    }.get(language, language.value)
    return (
        _GOAL_COMPLETION_LEDGER_HUMAN_BASE
        + f" Write user-facing prose in {display} ({language.value})."
    )


def _append_goal_completion_ledger_pair(
    *,
    state: LoopState,
    iteration_completed: int,
    action: CompletionStrategy,
    final_output: str | None,
    context_engine: Any | None = None,
) -> None:
    """Append RFC-214 Human–AI pair for the goal completion report.

    Every completion strategy (``synthesize``, ``ledger_direct``) writes
    an independent ``goal_completion`` unit so the ledger has one canonical terminal
    report per goal regardless of how the text was produced.

    Args:
        state: Loop state whose ``loop_messages`` list is extended.
        iteration_completed: Iteration index that just finished (before ``state.iteration`` bump).
        action: Completion strategy used for this goal (logged at record sites only).
        final_output: Final user-visible text (may be empty).
        context_engine: ContextEngine instance for direct LedgerManager writes.
    """
    from soothe.foundation.sloop.utils.messages import _record_ledger_message

    _ = action
    text = (final_output or "").strip()
    if not text:
        return
    human_msg = LoopHumanMessage(
        content=_goal_completion_ledger_human_content(state),
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


_GOAL_COMPLETION_TAIL_PERSIST_TIMEOUT_SECONDS = 120.0


async def _goal_completion_tail_persistence(
    *,
    context_engine: Any | None,
    state_manager: Any,
    goal_record: Any,
    full_output: str | None,
    loop_state: LoopState,
    loop_id: str,
) -> list[str]:
    """Persist CE + checkpoint tail state after the ``completed`` wire event."""
    failures: list[str] = []
    unified_pg = getattr(state_manager, "_backend_type", None) == "postgresql"

    try:
        await state_manager.finalize_goal(
            goal_record,
            full_output,
            loop_state=loop_state,
            skip_persist=True,
        )
    except Exception as exc:
        failures.append(f"checkpoint_finalize:{type(exc).__name__}")
        logger.warning(
            "Goal-completion in-memory finalize failed for loop %s",
            loop_id,
            exc_info=True,
        )
        return failures

    if unified_pg:
        dag = None
        ledger: list[dict[str, Any]] | None = None
        if context_engine is not None:
            try:
                dag, ledger = context_engine.persistence_snapshot()
            except Exception as exc:
                failures.append(f"ce_snapshot:{type(exc).__name__}")
                logger.warning(
                    "Goal-completion CE snapshot failed for loop %s",
                    loop_id,
                    exc_info=True,
                )
        try:
            result = await state_manager.persist_goal_boundary_durable(
                dag=dag,
                ledger=ledger,
            )
            if not result.ok:
                failures.extend(result.failures)
        except Exception as exc:
            failures.append(f"goal_boundary:{type(exc).__name__}")
            logger.warning(
                "Goal-completion durable persist failed for loop %s",
                loop_id,
                exc_info=True,
            )
        return failures

    # SQLite: separate CE save and checkpoint flush.
    if context_engine is not None:
        try:
            await context_engine.save()
        except Exception as exc:
            failures.append(f"ce_save:{type(exc).__name__}")
            logger.warning(
                "Goal-completion CE save failed for loop %s",
                loop_id,
                exc_info=True,
            )
    try:
        checkpoint = getattr(state_manager, "_checkpoint", None)
        if checkpoint is not None:
            await state_manager.save(checkpoint)
        await state_manager.force_flush()
    except Exception as exc:
        failures.append(f"checkpoint_finalize:{type(exc).__name__}")
        logger.warning(
            "Goal-completion checkpoint flush failed for loop %s",
            loop_id,
            exc_info=True,
        )
    return failures


def _start_goal_completion_tail_persistence(
    ctx: LoopRuntimeContext,
    *,
    goal_record: Any,
    full_output: str | None,
) -> None:
    """Start tail persistence without blocking the ``completed`` wire event."""
    loop_id = str(getattr(ctx.state_manager, "loop_id", "unknown"))

    async def _run_tail() -> None:
        failures = await _goal_completion_tail_persistence(
            context_engine=ctx.ce,
            state_manager=ctx.state_manager,
            goal_record=goal_record,
            full_output=full_output,
            loop_state=ctx.loop_state,
            loop_id=loop_id,
        )
        if failures:
            logger.warning(
                "Goal-completion tail persistence incomplete for loop %s (%s)",
                loop_id,
                ", ".join(failures),
            )

    prior = ctx.tail_persistence_task
    if prior is not None and not prior.done():

        async def _run_chained() -> None:
            logger.info(
                "Chaining goal-completion tail persistence for loop %s",
                loop_id,
            )
            try:
                await asyncio.shield(prior)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug(
                    "Prior goal-completion tail persistence failed for loop %s",
                    loop_id,
                    exc_info=True,
                )
            await _run_tail()

        ctx.tail_persistence_task = asyncio.create_task(
            _run_chained(),
            name=f"goal-tail-persist-{loop_id[:12]}",
        )
        return

    ctx.tail_persistence_task = asyncio.create_task(
        _run_tail(),
        name=f"goal-tail-persist-{loop_id[:12]}",
    )


async def await_goal_completion_tail_persistence(
    ctx: LoopRuntimeContext | None,
    *,
    timeout_seconds: float = _GOAL_COMPLETION_TAIL_PERSIST_TIMEOUT_SECONDS,
) -> None:
    """Drain tail persistence before ``StrangeLoopStateManager.close()``."""
    if ctx is None:
        return
    task = ctx.tail_persistence_task
    if task is None or task.done():
        return

    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
    except TimeoutError:
        logger.warning(
            "Goal-completion tail persistence timed out after %.0fs for loop %s; cancelling",
            timeout_seconds,
            ctx.state_manager.loop_id,
        )
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    except Exception:
        logger.debug(
            "Goal-completion tail persistence failed for loop %s",
            ctx.state_manager.loop_id,
            exc_info=True,
        )


async def node_goal_completion(
    ctx: LoopRuntimeContext, graph_state: dict[str, Any]
) -> dict[str, Any]:
    """Finalize goal when planner reports ``done`` (record iteration, synthesis, emit completed).

    IG-475: Clear all pending execution state to prevent task leakage into next query.
    When goal completion happens, any pending decision, step_results, or working memory
    from this query must be cleared so the next query starts fresh.
    """
    strange_loop = ctx.strange_loop
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

    await ctx.emit(
        "plan_phase_status",
        {
            "label": _GOAL_FINALIZE_STATUS_LABEL,
            "total_tokens_used": ctx.loop_state.total_tokens_used,
        },
    )

    perf_start = ctx.scratch.iteration_perf_start or time.perf_counter()

    state.previous_plan = plan_result
    # RFC-226 terminal bootstrap: record_iteration already checkpointed this cycle.
    iteration_already_recorded = graph_state.get("after_record_route") == "goal_completion"
    if iteration_already_recorded:
        iteration_completed = max(state.iteration - 1, 0)
        logger.debug(
            "[goal_completion] Skipping duplicate iteration checkpoint (terminal bootstrap, iter=%d)",
            iteration_completed,
        )
    else:
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

    if not iteration_already_recorded:
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
        strange_loop.goal_synthesis_model(),
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

    # RFC-624 Phase 4: in-memory goal finalization only; disk persist runs after ``completed``.
    if ctx.ce is not None:
        try:
            await ctx.ce.finalize_goal(ctx.ce_goal_id, status="completed")
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
        if not (final_output or "").strip():
            logger.info(
                "Goal completion: ledger_direct empty; falling back to synthesis",
            )
            action = CompletionStrategy.SYNTHESIZE
            final_output = None
        else:
            logger.info(
                "Goal completion: action=ledger_direct chars=%d",
                len(final_output),
            )

    if action == CompletionStrategy.SYNTHESIZE:
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

        final_output = reconcile_synthesis_with_step_ledger(
            final_output,
            loop_messages=await state.get_loop_messages(),
        )

        logger.info(
            "Synthesis stream: chunks=%d ai_msgs=%d chars=%d",
            chunk_count,
            accum.ai_msg_count,
            len(final_output or ""),
        )

        if not (final_output or "").strip():
            used_synthesis_fallback = True
            final_output = generate_user_fallback_summary(state, plan_result)
            logger.info(
                "Goal completion: synthesis fallback chars=%d",
                len(final_output or ""),
            )

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

    logger.info(
        "Goal completed: iterations=%d duration=%dms action=%s",
        state.iteration,
        state.total_duration_ms,
        action.value,
    )

    _start_goal_completion_tail_persistence(
        ctx,
        goal_record=goal_record,
        full_output=updated_result.full_output,
    )
    # IG-475: Force garbage collection after goal completion to reclaim
    # LLM streaming objects (langchain message buffers, tokenizer caches, etc.)
    # This prevents accumulation of ephemeral objects across multiple queries.
    gc.collect()
    out: dict[str, Any] = {"last_outcome": "completed"}
    return out
