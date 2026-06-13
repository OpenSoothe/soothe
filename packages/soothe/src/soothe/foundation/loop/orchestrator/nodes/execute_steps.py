"""Execute planned steps via CoreAgent (RFC-220 ``execute``, RFC-622 relay)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from soothe.foundation.events.constants import STRANGE_LOOP_CONTEXT_COMPACTED
from soothe.foundation.loop.clarification import (
    ClarificationCapture,
    ClarificationDetector,
    ClarificationRequest,
    LoopStateView,
    answer_from_state,
    request_to_state,
)
from soothe.foundation.loop.engine.context_window_manager import ContextWindowManager
from soothe.foundation.loop.engine.executor import Executor, StepWaveQueued, StepWaveStart
from soothe.foundation.loop.state.schemas import LoopState, StepAction, StepResult
from soothe.foundation.loop.utils.messages import LoopAIMessage, LoopHumanMessage

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LEN = 3
_RECENT_STEP_OUTPUTS_CAP = 8

PLANNER_ASK_INTERRUPT_PREFIX = "planner-ask:"
"""Sentinel prefix marking a clarification request that came from a planner-emitted
``kind="ask_user"`` step rather than a real CoreAgent ``ask_user`` interrupt.
On answer arrival, ``node_execute`` synthesizes a ``StepResult`` for the matching
step id instead of trying to resume a CoreAgent interrupt that never existed."""


def _build_loop_state_view(ctx: LoopRuntimeContext) -> LoopStateView:
    state = ctx.loop_state
    goal_record = ctx.goal_record
    plan_result = ctx.scratch.plan_result
    recent: list[str] = []
    for sr in state.step_results[-_RECENT_STEP_OUTPUTS_CAP:]:
        try:
            recent.append(sr.to_evidence_string(truncate=True))
        except AttributeError:
            recent.append(str(getattr(sr, "output", "")))
    plan_summary: str | None = None
    if plan_result is not None:
        plan_summary = getattr(plan_result, "plan_reasoning", None) or getattr(
            plan_result, "next_action", None
        )
    # goal_user_submission holds the original user line (set by strange_loop.continue_goal).
    # Fall back to goal when goal_user_submission is None (e.g. autopilot or legacy paths).
    user_request = getattr(state, "goal_user_submission", None) or getattr(state, "goal", "")
    return LoopStateView(
        goal_id=getattr(goal_record, "goal_id", "") or "",
        goal_description=getattr(goal_record, "goal_description", "") or getattr(state, "goal", ""),
        user_request=user_request,
        iteration=getattr(state, "iteration", 0),
        intent_classification=getattr(state, "intent_classification", None),
        plan_summary=plan_summary,
        recent_step_outputs=tuple(recent),
        workspace_summary=getattr(state, "workspace", None),
        active_skills=tuple(getattr(state, "activated_skill_names", []) or []),
        active_mcp_servers=tuple(getattr(state, "active_mcp_servers", []) or []),
    )


def _is_rate_limit_error(error: str | None) -> bool:
    """Check if an error message indicates a rate limit (429) failure."""
    if not error:
        return False
    lower = error.lower()
    return "429" in lower or "rate limit" in lower or "throttling" in lower


def _format_ask_user_questions(questions: tuple[str, ...]) -> str:
    if not questions:
        return "(no questions captured)"
    return "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))


def _format_ask_user_answers(
    questions: tuple[str, ...],
    answers: tuple[str, ...],
    *,
    source: str,
    confidence: float | None,
) -> str:
    header = f"Answered (source={source or 'unknown'}"
    if confidence is not None:
        header += f", confidence={confidence:.2f}"
    header += "):"
    if not answers:
        return f"{header}\n(no answers captured)"
    pairs = []
    for idx, ans in enumerate(answers, 1):
        question = questions[idx - 1] if idx - 1 < len(questions) else ""
        if question:
            pairs.append(f"{idx}. Q: {question}\n   A: {ans}")
        else:
            pairs.append(f"{idx}. A: {ans}")
    return f"{header}\n" + "\n".join(pairs)


def _append_ask_user_loop_messages(
    state: LoopState,
    *,
    step_id: str,
    description: str,
    questions: tuple[str, ...],
    answers: tuple[str, ...],
    source: str,
    confidence: float | None,
    context_engine: Any | None = None,
) -> None:
    """Mirror the executor (Execute → AI) ledger pattern for ask_user steps.

    plan-assess / plan-generate consume ``state.loop_messages`` to ground the
    next planning iteration. Without this pair the planner re-asks the same
    clarification because it has no record of what was asked or answered.
    """
    from soothe.foundation.loop.utils.messages import _record_ledger_message

    questions_block = _format_ask_user_questions(questions)
    answers_block = _format_ask_user_answers(
        questions, answers, source=source, confidence=confidence
    )
    human = LoopHumanMessage(
        content=f"Execute: {description}\nQuestions:\n{questions_block}",
        thread_id=state.thread_id,
        iteration=state.iteration,
        goal_summary=(state.goal[:200] if state.goal else None),
        workspace=state.workspace,
        phase="execute_step",
        step_id=step_id,
    )
    ai = LoopAIMessage(
        content=answers_block,
        thread_id=state.thread_id,
        iteration=state.iteration,
        phase="execute_step",
        step_id=step_id,
    )
    _record_ledger_message(context_engine, human, "execute_step", state.loop_messages)
    _record_ledger_message(context_engine, ai, "execute_step", state.loop_messages)


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

    payload: dict[str, Any] = {
        "step_id": result.step_id,
        "success": result.success,
        "output_preview": output_preview,
        "error": result.error or None,
        "duration_ms": result.duration_ms,
        "tool_call_count": result.tool_call_count,
    }
    # Surface ask_user Q&A on the event so the TUI can render the resolved
    # question/answer pair on the step card.
    if isinstance(result.outcome, dict) and result.outcome.get("kind") == "ask_user":
        clarification: dict[str, Any] = {
            "questions": list(result.outcome.get("questions") or ()),
            "answers": list(result.outcome.get("answers") or ()),
            "source": str(result.outcome.get("source") or ""),
        }
        confidence = result.outcome.get("confidence")
        if confidence is not None:
            clarification["confidence"] = float(confidence)
        payload["clarification"] = clarification

    await ctx.emit("step_completed", payload)


async def node_execute(ctx: LoopRuntimeContext, state_dict: dict[str, Any]) -> dict[str, Any]:
    """Run ready steps, stream events, apply step results to ``LoopState``."""
    strange_loop = ctx.strange_loop
    strange_loop = strange_loop  # Legacy alias for backward compat
    state = ctx.loop_state
    state_manager = ctx.state_manager
    goal_context_manager = ctx.goal_context_manager
    goal_record = ctx.goal_record
    checkpoint = ctx.checkpoint
    decision = ctx.scratch.decision
    plan_result = ctx.scratch.plan_result

    # RFC-622: consume any answer left by a prior await_clarification visit.
    resume_answer_payload: dict[str, Any] | None = None
    planner_ask_answered_step_id: str | None = None
    planner_ask_answers: tuple[str, ...] = ()
    planner_ask_source: str = ""
    planner_ask_questions: tuple[str, ...] = ()
    planner_ask_confidence: float | None = None
    pending_answer_state = state_dict.get("pending_clarification_answer")
    pending_request_state = state_dict.get("pending_clarification")
    if pending_answer_state and pending_request_state:
        try:
            ans = answer_from_state(pending_answer_state)
            origin_iid = str(pending_request_state.get("origin_interrupt_id", ""))
            if origin_iid.startswith(PLANNER_ASK_INTERRUPT_PREFIX):
                # IG-462 Branch 1: planner-emitted ask_user step. No CoreAgent
                # interrupt to resume — instead synthesize a StepResult below
                # so the next get_ready_steps() call naturally skips this step.
                planner_ask_answered_step_id = origin_iid[len(PLANNER_ASK_INTERRUPT_PREFIX) :]
                planner_ask_answers = tuple(ans.answers)
                planner_ask_source = ans.source
                planner_ask_questions = tuple(
                    str(q) for q in (pending_request_state.get("questions") or ())
                )
                planner_ask_confidence = ans.confidence
            elif origin_iid:
                resume_answer_payload = {origin_iid: {"answers": list(ans.answers)}}
        except (ValueError, TypeError):
            logger.exception("[execute] malformed pending_clarification_answer; ignoring")

    if decision is None or plan_result is None:
        # RFC-622 resume path: when ``Command(resume=...)`` re-enters the
        # graph after a clarification interrupt, ``ctx.scratch`` is freshly
        # initialized for the new ``ainvoke`` call so the prior plan-phase
        # decision is gone. We can still synthesize the answered step's
        # result from state alone — the next iteration's plan_assess /
        # plan_generate will rebuild a decision before any new execution.
        if planner_ask_answered_step_id is not None:
            outcome_payload: dict[str, Any] = {
                "kind": "ask_user",
                "answers": list(planner_ask_answers),
                "source": planner_ask_source,
                "questions": list(planner_ask_questions),
            }
            if planner_ask_confidence is not None:
                outcome_payload["confidence"] = planner_ask_confidence
            synth_result = StepResult(
                step_id=planner_ask_answered_step_id,
                success=True,
                duration_ms=0,
                thread_id=state.thread_id,
                outcome=outcome_payload,
                tool_call_count=0,
            )
            ask_description = "Ask user clarifying question"
            step_desc_local = {planner_ask_answered_step_id: ask_description}
            _append_ask_user_loop_messages(
                state,
                step_id=planner_ask_answered_step_id,
                description=ask_description,
                questions=planner_ask_questions,
                answers=planner_ask_answers,
                source=planner_ask_source,
                confidence=planner_ask_confidence,
                context_engine=ctx.ce,
            )
            await _record_and_emit_step_completed(
                ctx, result=synth_result, step_desc=step_desc_local
            )
            # Resume synth skips record_iteration, where plan_manager normally
            # records step outcomes into the DAG. Without this call the
            # ask_user step would remain PENDING in the plan DAG forever and
            # surface in the goal_completion report even though the user
            # already answered.
            try:
                ctx.plan_manager.record_step_outcomes([synth_result])
            except Exception:
                logger.exception(
                    "[execute] plan_manager.record_step_outcomes failed for resumed step %s",
                    planner_ask_answered_step_id,
                )
            logger.info(
                "[execute] resumed clarification answer (no scratch decision); "
                "synthesized step_completed for %s, deferring further execution to next iteration",
                planner_ask_answered_step_id,
            )
            # Advance the iteration counter inline since we are skipping
            # record_iteration on this resume path. Without this, iteration_gate
            # would loop (or never terminate via max_iterations) because no
            # iteration was recorded as complete during this graph invocation.
            state.iteration += 1
            # Mirror the appended Q&A pair (and updated iteration) onto
            # goal_record.loop_messages and persist. The synth path skips
            # record_iteration, where plan-phase / execute pairs are normally
            # snapshotted onto the goal record. Without this save, the next
            # clarification round trip reloads goal_record with a stale
            # ledger and plan-assess / plan-generate re-ask the same
            # question because the prior answers are gone.
            if goal_record is not None:
                goal_record.loop_messages = [m.model_copy(deep=True) for m in state.loop_messages]
                goal_record.iteration = state.iteration
                try:
                    await state_manager.save(checkpoint)
                except Exception:
                    logger.exception(
                        "[execute] failed to persist synth-path Q&A ledger for step %s",
                        planner_ask_answered_step_id,
                    )
            return {
                "pending_clarification": None,
                "pending_clarification_answer": None,
                "last_outcome": "continue",
                "resume_synth": True,
            }
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

    # IG-462 Branch 1 continued: synthesize a successful StepResult for the
    # planner-emitted ask_user step that was just answered. Recording it here
    # adds the id to state.completed_step_ids so the executor's
    # get_ready_steps() will skip it on the resumed wave.
    if planner_ask_answered_step_id is not None:
        ask_step = next(
            (s for s in decision.steps if s.id == planner_ask_answered_step_id),
            None,
        )
        outcome_payload: dict[str, Any] = {
            "kind": "ask_user",
            "answers": list(planner_ask_answers),
            "source": planner_ask_source,
            "questions": list(planner_ask_questions),
        }
        if planner_ask_confidence is not None:
            outcome_payload["confidence"] = planner_ask_confidence
        synth_result = StepResult(
            step_id=planner_ask_answered_step_id,
            success=True,
            duration_ms=0,
            thread_id=state.thread_id,
            outcome=outcome_payload,
            tool_call_count=0,
        )
        # Make the description available for the step_completed event even when
        # the answered step is not in decision.steps anymore.
        ask_description = (
            ask_step.description if ask_step is not None else "Ask user clarifying question"
        )
        step_desc.setdefault(planner_ask_answered_step_id, ask_description)
        step_results.append(synth_result)
        # Append the Q&A pair to the loop ledger so plan-assess and plan-generate
        # see the questions and resolved answers on the next iteration. Without
        # this the planner re-asks the same questions because the ledger only
        # carries executor-emitted (Execute → AI) pairs.
        _append_ask_user_loop_messages(
            state,
            step_id=planner_ask_answered_step_id,
            description=ask_description,
            questions=planner_ask_questions,
            answers=planner_ask_answers,
            source=planner_ask_source,
            confidence=planner_ask_confidence,
            context_engine=ctx.ce,
        )
        await _record_and_emit_step_completed(ctx, result=synth_result, step_desc=step_desc)

    # RFC-223: Pass checkpointer for thread fork inheritance
    checkpointer = strange_loop.core_agent.checkpointer

    # IG-462 Branch 2: when the planner emits a kind="ask_user" step in this
    # wave, surface it to the clarification relay BEFORE running the executor.
    # The planner prompt limits this to one ask_user per wave, paired with no
    # other steps; we honor that by short-circuiting on the first such ready
    # step. Other ready steps will run on the resumed wave once the answer
    # arrives.
    if ctx.clarification_policy is not None:
        ready_steps = decision.get_ready_steps(state.dependency_completion_ids())
        ask_step = next((s for s in ready_steps if s.kind == "ask_user"), None)
        if ask_step is not None and ask_step.questions:
            ask_view = _build_loop_state_view(ctx)
            ask_iid = f"{PLANNER_ASK_INTERRUPT_PREFIX}{ask_step.id}"
            ask_request = ClarificationRequest(
                questions=tuple(ask_step.questions),
                origin_node="execute",
                origin_interrupt_id=ask_iid,
                loop_state=ask_view,
            )
            logger.info(
                "[execute] planner-emitted ask_user step %s → routing to await_clarification (questions=%d)",
                ask_step.id,
                len(ask_step.questions),
            )
            # Emit step_started so live UIs surface the pending question;
            # _record_and_emit_step_completed will fire when the answer lands.
            await _emit_step_started_for_steps([ask_step])
            return {
                "pending_clarification": request_to_state(ask_request),
                "last_clarification_origin": "execute",
                "pending_clarification_answer": None,
            }

    clarification_capture = ClarificationCapture()
    clarification_detector: ClarificationDetector | None = None
    clarification_view: LoopStateView | None = None
    if ctx.clarification_policy is not None:
        clarification_detector = ClarificationDetector()
        clarification_view = _build_loop_state_view(ctx)

    run_executor = Executor(
        strange_loop.core_agent,
        checkpointer=checkpointer,
        max_parallel_steps=strange_loop.config.agent.loop.limits.max_parallel_steps,
        config=strange_loop.config,
        goal_context_manager=goal_context_manager,
        loop_id=ctx.state_manager.loop_id,
        clarification_detector=clarification_detector,
        clarification_capture=clarification_capture,
        clarification_loop_state_view=clarification_view,
        clarification_resume_answer_payload=resume_answer_payload,
        proposal_queue=ctx.proposal_queue,  # RFC-204 Group C
        context_engine=ctx.ce,  # RFC-624 Phase 4
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

    # Rate limit circuit breaker: track consecutive 429 failures
    _rate_limited = [r for r in step_results if _is_rate_limit_error(r.error)]
    _succeeded = [r for r in step_results if r.success]
    if _rate_limited and not _succeeded:
        checkpoint.thread_health_metrics.consecutive_rate_limit_errors += len(_rate_limited)
        logger.warning(
            "[Rate limit] %d step(s) rate-limited (consecutive=%d)",
            len(_rate_limited),
            checkpoint.thread_health_metrics.consecutive_rate_limit_errors,
        )
    elif _succeeded:
        checkpoint.thread_health_metrics.consecutive_rate_limit_errors = 0

    state.last_wave_tool_call_count = sum(r.tool_call_count for r in step_results)
    state.last_wave_subagent_task_count = sum(r.subagent_task_completions for r in step_results)
    state.last_wave_hit_subagent_cap = any(r.hit_subagent_cap for r in step_results)
    state.last_wave_hit_tool_budget = any(r.hit_tool_budget for r in step_results)

    state.previous_plan = plan_result

    ctx.scratch.step_results = step_results

    # RFC-224: Check context window and compact if needed
    if checkpointer is not None and strange_loop.config is not None:
        try:
            context_manager = ContextWindowManager(checkpointer, strange_loop.config)
            compaction_result = await context_manager.check_and_compact_if_needed(
                state.thread_id,
                state,
            )
            if compaction_result is not None:
                await ctx.emit(
                    STRANGE_LOOP_CONTEXT_COMPACTED,
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

    # RFC-622: surface a captured clarification so the graph routes to
    # ``await_clarification`` instead of ``record_iteration``.
    if clarification_capture.pending_request is not None:
        logger.info("[execute] clarification captured; routing to await_clarification")
        return {
            "pending_clarification": request_to_state(clarification_capture.pending_request),
            "last_clarification_origin": "execute",
            # Clear any prior answer so re-entry only consumes it once.
            "pending_clarification_answer": None,
        }

    if resume_answer_payload is not None or planner_ask_answered_step_id is not None:
        # Successfully resumed from a prior clarification (CoreAgent interrupt
        # or planner-emitted ask_user — IG-462). Clear BOTH the request and the
        # answer channels so route_after_execute does not re-route us back into
        # await_clarification on the next graph tick.
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
        }

    return {}
