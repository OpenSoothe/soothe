"""Loop graph node that resolves a pending clarification (RFC-622).

Invoked when a prior node set ``pending_clarification`` (execute ask_user,
plan-mode review, etc.). Dispatches to ``ClarificationPolicy``; on
success writes ``pending_clarification_answer``. On defer, parks via CE when
wired and sets ``last_outcome="deferred"`` while keeping graph pending.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.clarification.origins import ORIGIN_PLAN_MODE_REVIEW
from soothe.sloop.clarification.protocol import (
    ClarificationDeferredError,
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
    """Resolve a pending clarification by dispatching to the policy."""
    logger.info(
        "[await_clarification] node entered with pending=%s, answer=%s",
        bool(state.get("pending_clarification")),
        state.get("pending_clarification_answer"),
    )
    pending = state.get("pending_clarification")
    if not pending:
        logger.warning("[await_clarification] entered without pending_clarification; no-op")
        return {"pending_clarification": None}

    try:
        request = request_from_state(pending)
    except ValueError:
        logger.exception("[await_clarification] malformed pending_clarification")
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

    resume_turn = bool(
        (getattr(ctx, "clarification_resume_answers", None) or [])
        or (getattr(ctx, "clarification_resume_text", None) or "").strip()
    )
    if not resume_turn:
        await ctx.emit(_EVT_CLARIFICATION_REQUESTED, requested_payload)
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

    # Keep pending alongside the answer so the origin node can pair
    # origin_interrupt_id; that node clears both channels after consume.
    return {"pending_clarification_answer": answer_to_state(answer)}


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
    return {
        "pending_clarification_answer": None,
        "last_outcome": "deferred",
    }


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


def _summary(questions: tuple[str, ...]) -> str:
    joined = " | ".join(questions)
    if len(joined) <= _QUESTION_SUMMARY_CHARS:
        return joined
    return joined[: _QUESTION_SUMMARY_CHARS - 1] + "…"


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
