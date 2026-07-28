"""Loop graph node that resolves a pending clarification (RFC-622).

Invoked when a prior node (``execute``, StrangeLoop ``plan_generate`` /
``plan_assess``, or planner-subagent ``planner_subagent_review``) detected an
``ask_user`` interrupt / review gate and set ``pending_clarification``
on the loop state.

The node calls into the runtime's :class:`ClarificationPolicy`. On success
it writes ``pending_clarification_answer`` so the originating node can resume
CoreAgent with the answer. On :class:`ClarificationDeferredError` it marks
the goal as ``awaiting_clarification`` and terminates the loop with
``last_outcome="deferred"``.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.clarification.origins import ORIGIN_PLANNER_SUBAGENT_REVIEW
from soothe.sloop.clarification.protocol import (
    ClarificationDeferredError,
    answer_to_state,
    request_from_state,
)

from ..orchestrator.runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)

# Short event_type names emitted via ``ctx.emit``; the runner dispatch
# (``_runner_strange_loop.py``) wraps them in the corresponding wire events
# (``soothe.loop.clarification.*``) before yielding to the stream.
_EVT_CLARIFICATION_REQUESTED = "clarification_requested"
_EVT_CLARIFICATION_ANSWERED = "clarification_answered"
_EVT_CLARIFICATION_DEFERRED = "clarification_deferred"

_QUESTION_SUMMARY_CHARS = 240

# Internal event type for goal unblocked notification (RFC-622, RFC-625)
_EVT_GOAL_UNBLOCKED = "goal_unblocked"


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

    policy = ctx.clarification_policy
    if policy is None:
        logger.warning("[await_clarification] no clarification policy configured; deferring")
        await ctx.emit(
            _EVT_CLARIFICATION_DEFERRED,
            {
                "reason": "no clarification policy configured",
                "question_summary": _summary(request.questions),
            },
        )
        await ctx.mark_goal_status("awaiting_clarification", reason="no policy configured")
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_outcome": "deferred",
        }

    requested_payload: dict[str, Any] = {
        "questions": list(request.questions),
        "origin_node": request.origin_node,
        "mode": _mode_for_policy(policy, origin_node=request.origin_node),
    }
    if request.origin_node == ORIGIN_PLANNER_SUBAGENT_REVIEW:
        scratch = getattr(ctx, "scratch", None)
        plan_path = getattr(scratch, "plan_artifact_path", None)
        plan_markdown = getattr(scratch, "plan_artifact_markdown", None)
        if plan_path:
            requested_payload["plan_path"] = str(plan_path)
        if plan_markdown:
            requested_payload["plan_markdown"] = str(plan_markdown)
    await ctx.emit(_EVT_CLARIFICATION_REQUESTED, requested_payload)

    try:
        answer = await policy.answer(request)
    except ClarificationDeferredError as exc:
        logger.warning("[await_clarification] policy deferred (kind=%s): %s", exc.kind, exc.reason)
        await ctx.emit(
            _EVT_CLARIFICATION_DEFERRED,
            {
                "reason": exc.reason,
                "defer_kind": exc.kind,
                "question_summary": _summary(request.questions),
            },
        )
        await ctx.mark_goal_status("awaiting_clarification", reason=exc.reason)
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_outcome": "deferred",
        }

    await ctx.emit(
        _EVT_CLARIFICATION_ANSWERED,
        {
            "source": answer.source,
            "confidence": answer.confidence,
            "defer": answer.defer,
        },
    )

    # RFC-622 / RFC-625: Emit goal_unblocked event when clarification resolves
    # so AutopilotService can immediately trigger scheduling instead of waiting
    # for the next poll cycle. This is critical for responsive autopilot mode.
    # The goal was in awaiting_clarification (BLOCKED_STATES) and now transitions
    # back to pending (ready for scheduling).
    goal_id = getattr(request.loop_state, "goal_id", None)
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

    # IG-462: keep ``pending_clarification`` alive alongside the answer so the
    # originating node (``execute`` / ``plan_*``) can pair them on re-entry
    # — it needs ``origin_interrupt_id`` to know which CoreAgent interrupt
    # (or planner-emitted step) is being resumed. The originating node clears
    # both channels once it has consumed the pair.
    return {
        "pending_clarification_answer": answer_to_state(answer),
    }


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
