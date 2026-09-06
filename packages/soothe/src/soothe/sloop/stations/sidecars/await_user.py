"""Loop graph node that resolves a pending clarification."""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.clarification.origins import ORIGIN_PLAN_MODE_REVIEW
from soothe.sloop.clarification.protocol import (
    ClarificationDeferredError,
    answer_from_state,
    answer_to_state,
    request_from_state,
    request_to_state,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

_EVT_CLARIFICATION_REQUESTED = "clarification_requested"
_EVT_CLARIFICATION_ANSWERED = "clarification_answered"
_EVT_CLARIFICATION_DEFERRED = "clarification_deferred"
_EVT_GOAL_UNBLOCKED = "goal_unblocked"
_QUESTION_SUMMARY_CHARS = 240


async def node_await_clarification(
    ctx: LoopRuntimeContext, state: dict[str, Any]
) -> dict[str, Any]:
    """Resolve a pending clarification via the unified relay."""
    logger.info(
        "[await_clarification] node entered with pending=%s, answer=%s",
        bool(state.get("pending_clarification")),
        state.get("pending_clarification_answer"),
    )
    pending = state.get("pending_clarification")
    if not pending:
        queue = state.get("clarification_queue")
        if isinstance(queue, list) and queue:
            pending = queue[0]
    if not pending:
        logger.warning("[await_clarification] entered without pending_clarification; no-op")
        return {"pending_clarification": None}

    try:
        request = request_from_state(pending)
    except ValueError:
        logger.exception("[await_clarification] malformed pending_clarification")
        await ctx.emit(
            "fatal_error", {"error": "Malformed pending clarification state", "step_id": ""}
        )
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_outcome": "fatal",
        }

    pending_dict: dict[str, Any] = (
        dict(pending) if isinstance(pending, dict) else request_to_state(request)
    )

    policy = ctx.clarification_policy
    if policy is None:
        logger.warning("[await_clarification] no clarification policy configured; deferring")
        return await _hard_defer(
            ctx,
            pending_dict,
            reason="no clarification policy configured",
            defer_kind="explicit",
            questions=request.questions,
        )

    resume_turn = bool(
        (getattr(ctx, "clarification_resume_answers", None) or [])
        or (getattr(ctx, "clarification_resume_text", None) or "").strip()
    )

    if not resume_turn:
        # Fresh request: emit, save CE, mark goal, then delegate to relay.park().
        requested_payload: dict[str, Any] = {
            "questions": list(request.questions),
            "origin_node": request.origin_node,
            "mode": _mode_for_policy(policy, origin_node=request.origin_node),
        }
        if request.origin_node == ORIGIN_PLAN_MODE_REVIEW:
            _attach_plan_review_payload(requested_payload, ctx, pending)
        resume_ticket = state.get("resume_ticket") or getattr(
            getattr(ctx, "loop_state", None), "resume_ticket", None
        )
        if resume_ticket is not None:
            rt_step_id = (
                resume_ticket.get("step_id")
                if isinstance(resume_ticket, dict)
                else getattr(resume_ticket, "step_id", None)
            )
            if rt_step_id:
                requested_payload["step_id"] = str(rt_step_id)
        await ctx.emit(_EVT_CLARIFICATION_REQUESTED, requested_payload)

        if ctx.ce is not None:
            try:
                await ctx.ce.save()
            except Exception:
                logger.warning("[await_clarification] CE save before park failed", exc_info=True)
        goal_record = getattr(ctx, "goal_record", None)
        if goal_record is not None:
            try:
                await ctx.state_manager.mark_goal_awaiting_clarification(
                    goal_record, reason=request.origin_node or "clarification"
                )
            except Exception:
                logger.warning("[await_clarification] mark_goal failed", exc_info=True)

        # Delegate to the unified relay. The relay calls the policy
        # internally, stores the row, and marks the CE goal. The node
        # already emitted + saved CE + marked the loop checkpoint.
        if ctx.relay is not None and ctx.relay.pending_handle is not None:
            outcome = await ctx.relay.park(
                ctx.relay.pending_handle,
                policy=policy,
                ce=ctx.ce,
                emit=None,
            )
            ctx.relay.pending_handle = None
            if outcome.kind in ("awaiting_human", "deferred"):
                if outcome.kind == "deferred":
                    await ctx.emit(
                        _EVT_CLARIFICATION_DEFERRED,
                        {
                            "reason": "relay deferred",
                            "defer_kind": outcome.defer_kind or "explicit",
                            "questions": list(request.questions),
                        },
                    )
                return {"pending_clarification_answer": None, "last_outcome": "deferred"}
            answer = outcome.answer
            if answer is None:
                return await _hard_defer(
                    ctx,
                    pending_dict,
                    reason="relay returned no answer",
                    defer_kind="explicit",
                    questions=request.questions,
                )
        else:
            # Fallback: no relay handle — call the policy directly.
            try:
                answer = await policy.answer(request)
            except ClarificationDeferredError as exc:
                return await _hard_defer(
                    ctx,
                    pending_dict,
                    reason=exc.reason,
                    defer_kind=exc.kind,
                    questions=request.questions,
                )
            if answer.defer:
                return await _hard_defer(
                    ctx,
                    pending_dict,
                    reason="policy deferred",
                    defer_kind=str(answer.audit.get("defer_kind", "explicit")),
                    questions=request.questions,
                )
    else:
        # Resume turn: the answer is in state from graph_input.
        # Consume the relay row and decode the answer.
        logger.info("[await_clarification] resume turn (origin=%s)", request.origin_node)
        relay_id = state.get("resume_relay_id") or ""
        if relay_id and ctx.relay is not None:
            try:
                await ctx.relay.consume(relay_id=relay_id)
            except Exception:
                logger.warning(
                    "[await_clarification] relay consume failed (relay=%s)",
                    relay_id[:12],
                    exc_info=True,
                )
        pending_answer = state.get("pending_clarification_answer")
        if pending_answer is not None:
            answer = answer_from_state(pending_answer)
        else:
            # No answer in state — call the policy as fallback.
            answer = await policy.answer(request)

    # Success path: emit answered, resolve CE park, clear resume flags.
    await ctx.emit(
        _EVT_CLARIFICATION_ANSWERED,
        {
            "source": answer.source,
            "confidence": answer.confidence,
            "defer": False,
        },
    )

    unblocked = await ctx.resolve_parked_clarification(list(answer.answers))
    if unblocked:
        goal_id = getattr(request.loop_state, "goal_id", None) or getattr(ctx, "ce_goal_id", None)
        loop_id = getattr(ctx.state_manager, "loop_id", None)
        if goal_id:
            await ctx.emit(
                _EVT_GOAL_UNBLOCKED,
                {
                    "goal_id": goal_id,
                    "old_status": "awaiting_clarification",
                    "new_status": "pending",
                    "reason": "clarification resolved",
                    "loop_id": loop_id,
                },
            )

    if resume_turn:
        ctx.clarification_resume_answers = None
        ctx.clarification_resume_text = None

    loop_state = getattr(ctx, "loop_state", None)
    if loop_state is not None:
        history = list(getattr(loop_state, "clarification_history", []) or [])
        history.append(
            {
                "questions": list(request.questions),
                "answers": list(answer.answers),
                "source": answer.source,
                "confidence": answer.confidence,
            }
        )
        if len(history) > 20:
            history = history[-20:]

    result: dict[str, Any] = {"pending_clarification_answer": answer_to_state(answer)}
    if loop_state is not None:
        result["clarification_history"] = history
    return result


async def _hard_defer(
    ctx: LoopRuntimeContext,
    pending: dict[str, Any],
    *,
    reason: str,
    defer_kind: str,
    questions: tuple[str, ...],
) -> dict[str, Any]:
    await ctx.emit(
        _EVT_CLARIFICATION_DEFERRED,
        {
            "reason": reason,
            "defer_kind": defer_kind,
            "question_summary": _summary(questions),
            "questions": list(questions),
        },
    )
    await ctx.park_for_clarification(pending, reason=reason)
    if ctx.ce is not None:
        try:
            await ctx.ce.save()
        except Exception:
            logger.warning("[await_clarification] CE save on park failed", exc_info=True)
    return {"pending_clarification_answer": None, "last_outcome": "deferred"}


def _attach_plan_review_payload(
    payload: dict[str, Any], ctx: LoopRuntimeContext, pending: Any
) -> None:
    scratch = getattr(ctx, "scratch", None)
    plan_path = getattr(scratch, "plan_draft_path", None)
    plan_markdown = getattr(scratch, "plan_draft_markdown", None)
    if not plan_path and isinstance(pending, dict):
        plan_path = pending.get("plan_path")
    if not plan_markdown and isinstance(pending, dict):
        plan_markdown = pending.get("plan_markdown")
    if plan_path:
        payload["plan_path"] = str(plan_path)
    if plan_markdown:
        payload["plan_markdown"] = str(plan_markdown)


def _summary(questions: tuple) -> str:
    parts = [_question_text(q) for q in questions]
    joined = " | ".join(parts)
    if len(joined) <= _QUESTION_SUMMARY_CHARS:
        return joined
    return joined[: _QUESTION_SUMMARY_CHARS - 1] + "…"


def _question_text(question: Any) -> str:
    if isinstance(question, dict):
        return str(question.get("question") or question.get("header") or "")
    return str(question)


def _mode_for_policy(policy: Any, *, origin_node: str | None = None) -> str:
    from soothe.sloop.clarification.auto import AutoClarificationPolicy
    from soothe.sloop.clarification.interactive import InteractiveClarificationPolicy

    if isinstance(policy, InteractiveClarificationPolicy):
        return "manual"
    requires_manual = getattr(policy, "requires_manual", None)
    if isinstance(policy, AutoClarificationPolicy) or callable(requires_manual):
        if callable(requires_manual) and origin_node and requires_manual(origin_node):
            return "manual"
        return "auto"
    return "manual"
