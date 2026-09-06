"""Loop graph node that resolves a pending clarification."""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.clarification.origins import ORIGIN_PLAN_MODE_REVIEW
from soothe.sloop.clarification.protocol import (
    ClarificationDeferredError,
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
    """Resolve a pending clarification by dispatching to the policy."""
    logger.info(
        "[await_clarification] node entered with pending=%s, answer=%s",
        bool(state.get("pending_clarification")) or _relay_has_pending(state),
        state.get("pending_clarification_answer"),
    )
    # Hydrate the relay from the relay_state channel so a fresh ainvoke
    # reconstructs the inbox + scratch from the checkpoint.
    relay = getattr(ctx, "relay", None)
    relay_state = state.get("relay_state")
    if relay is not None and isinstance(relay_state, dict):
        relay.hydrate_from_channels(relay_state, scratch=ctx.scratch)
    pending = _head_pending_request(state, relay)
    if pending is None:
        logger.warning("[await_clarification] entered without pending clarification; no-op")
        return {"relay_state": {}}

    try:
        request = request_from_state(pending)
    except ValueError:
        logger.exception("[await_clarification] malformed pending_clarification")
        await ctx.emit(
            "fatal_error",
            {"error": "Malformed pending clarification state", "step_id": ""},
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

    requested_payload: dict[str, Any] = {
        "questions": list(request.questions),
        "origin_node": request.origin_node,
        "mode": _mode_for_policy(policy, origin_node=request.origin_node),
    }
    if request.origin_node == ORIGIN_PLAN_MODE_REVIEW:
        _attach_plan_review_payload(requested_payload, ctx, pending)

    # Surface the paused step id so the TUI can show "awaiting answer" on the
    # existing step card instead of marking it complete. The resume ticket is
    # carried on the relay inbox head (projected by node_execute on capture).
    resume_ticket = None
    if relay is not None and relay.inbox.head_ticket is not None:
        resume_ticket = relay.inbox.head_ticket
    if resume_ticket is None:
        resume_ticket = getattr(getattr(ctx, "loop_state", None), "resume_ticket", None)
    if resume_ticket is not None:
        rt_step_id = (
            resume_ticket.get("step_id")
            if isinstance(resume_ticket, dict)
            else getattr(resume_ticket, "step_id", None)
        )
        if rt_step_id:
            requested_payload["step_id"] = str(rt_step_id)

    resume_turn = bool(
        (getattr(ctx, "clarification_resume_answers", None) or [])
        or (getattr(ctx, "clarification_resume_text", None) or "").strip()
    )
    if not resume_turn:
        await ctx.emit(_EVT_CLARIFICATION_REQUESTED, requested_payload)
        # The interactive policy pauses on a LangGraph ``interrupt`` below —
        # the graph channels survive via the checkpointer, but dispatch's CE
        # step DAG is in-memory only. Save now or the resume loads an empty
        # DAG and root_eval fatals on a not-green action tree.
        if ctx.ce is not None:
            try:
                await ctx.ce.save()
            except Exception:
                logger.warning("[await_clarification] CE save before pause failed", exc_info=True)
        # Mark the goal index as parked so the orphan-loop repair on the
        # next worker load preserves the running state. The manual path
        # pauses inside `policy.answer` below via a LangGraph interrupt
        # and does not flow through `park_for_clarification`.
        goal_record = getattr(ctx, "goal_record", None)
        if goal_record is not None:
            try:
                await ctx.state_manager.mark_goal_awaiting_clarification(
                    goal_record,
                    reason=request.origin_node or "clarification",
                )
            except Exception:
                logger.warning(
                    "[await_clarification] mark_goal_awaiting_clarification failed",
                    exc_info=True,
                )
    else:
        logger.info(
            "[await_clarification] resume turn; skipping clarification_requested re-emit "
            "(origin=%s)",
            request.origin_node,
        )

    try:
        answer = await policy.answer(request)
    except ClarificationDeferredError as exc:
        logger.warning("[await_clarification] policy deferred (kind=%s): %s", exc.kind, exc.reason)
        return await _hard_defer(
            ctx,
            pending_dict,
            reason=exc.reason,
            defer_kind=exc.kind,
            questions=request.questions,
        )

    if answer.defer:
        logger.warning(
            "[await_clarification] policy returned defer=True (source=%s); parking",
            answer.source,
        )
        return await _hard_defer(
            ctx,
            pending_dict,
            reason="policy returned defer=True",
            defer_kind="explicit",
            questions=request.questions,
        )

    await ctx.emit(
        _EVT_CLARIFICATION_ANSWERED,
        {
            "source": answer.source,
            "confidence": answer.confidence,
            "defer": answer.defer,
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
            logger.info(
                "[await_clarification] clarification resolved, goal %s unblocked (loop=%s)",
                goal_id,
                loop_id,
            )

    if resume_turn:
        ctx.clarification_resume_answers = None
        ctx.clarification_resume_text = None

    # Append to clarification history so veritas can reference prior Q&A
    # in subsequent clarifications for the same goal (RFC-622 enhancement).
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
        # Cap at 20 entries to bound memory.
        if len(history) > 20:
            history = history[-20:]

    # Project the answer into relay_state so the relay owns the write path.
    # The origin node (execute / plan_review) consumes via relay.consume_answer.
    result: dict[str, Any] = {}
    if relay is not None:
        result.update(relay.record_answer(answer=answer, scratch=ctx.scratch))
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
    relay = getattr(ctx, "relay", None)
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
    # The execute→await_user path skips record_iteration, the only other CE
    # save after graph start. Without this save the step DAG (and the parked
    # status) stay in-memory; the resume turn loads an empty DAG, the synth
    # completes a missing step, and root_eval fatals on a not-green tree.
    if ctx.ce is not None:
        try:
            await ctx.ce.save()
        except Exception:
            logger.warning("[await_clarification] CE save on park failed", exc_info=True)
    result: dict[str, Any] = {
        "pending_clarification_answer": None,
        "last_outcome": "deferred",
    }
    if relay is not None:
        result.update(relay.project_to_channels(scratch=ctx.scratch, mark_parked_head=True))
    return result


def _relay_has_pending(state: dict[str, Any]) -> bool:
    """True when the relay_state channel has an unanswered head entry."""
    relay_state = state.get("relay_state")
    if not isinstance(relay_state, dict):
        return False
    inbox = relay_state.get("inbox")
    return isinstance(inbox, list) and bool(inbox)


def _head_pending_request(
    state: dict[str, Any],
    relay: Any,
) -> dict[str, Any] | None:
    """Read the head clarification request from the `relay_state` channel."""
    relay_state = state.get("relay_state")
    if isinstance(relay_state, dict):
        inbox = relay_state.get("inbox")
        if isinstance(inbox, list) and inbox:
            head = inbox[0]
            if isinstance(head, dict):
                request = head.get("request")
                if isinstance(request, dict):
                    return request
    return None


def _attach_plan_review_payload(
    payload: dict[str, Any],
    ctx: LoopRuntimeContext,
    pending: Any,
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
    # RFC-622 §9c: questions may be QuestionSpec.model_dump() dicts, not just strings.
    parts = [_question_text(q) for q in questions]
    joined = " | ".join(parts)
    if len(joined) <= _QUESTION_SUMMARY_CHARS:
        return joined
    return joined[: _QUESTION_SUMMARY_CHARS - 1] + "…"


def _question_text(question: Any) -> str:
    """Render a structured question or plain string as text."""
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
