"""Conditional edges for the Loop Graph (RFC-904, RFC-622)."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END

from .stations import (
    AWAIT_USER,
    DELEGATE,
    DISPATCH,
    EXECUTE,
    FINALIZE,
    PLAN_REVIEW,
    RECONCILE,
    RECORD_PROGRESS,
    ROOT_EVAL,
)

logger = logging.getLogger(__name__)


def _pending_clarification(state: dict[str, Any]) -> bool:
    """True when a clarification request is pending and unanswered."""
    pending = state.get("pending_clarification")
    answer = state.get("pending_clarification_answer")
    return bool(pending) and not answer


def route_after_preprocess(state: dict[str, Any]) -> str:
    """Branch after enter_loop: chitchat END, wired delegate, or DISPATCH.

    The chitchat fast-path ENDs the graph here unconditionally. Whether a
    chitchat message should bypass the fast-path at all is decided upstream in
    ``enter_loop`` via ``should_bypass_chitchat_fast_path`` (loop-control phrase
    + intra-loop checkpoint work) — the sole bypass authority. Routing must
    not re-litigate that decision.
    """
    label = state.get("intake_label")

    if state.get("intent_route") == "fast_path":
        logger.debug("[routing] route_after_preprocess → END (chitchat fast-path)")
        return END

    if state.get("intent_route") == "wired_subagent":
        logger.debug("[routing] route_after_preprocess → delegate")
        return DELEGATE

    logger.debug(
        "[routing] route_after_preprocess → dispatch (label=%s)",
        getattr(label, "value", label),
    )
    return DISPATCH


def route_after_dispatch(state: dict[str, Any]) -> str:
    """DISPATCH → EXECUTE | ROOT_EVAL | END."""
    route = state.get("dispatch_route")
    if route == "root_eval":
        return ROOT_EVAL
    if route == "fatal" or state.get("last_outcome") == "fatal":
        return END
    return EXECUTE


def route_after_reconcile(state: dict[str, Any]) -> str:
    """RECONCILE → DISPATCH | ROOT_EVAL."""
    if state.get("reconcile_route") == "dispatch":
        return DISPATCH
    return ROOT_EVAL


def route_after_root_eval(state: dict[str, Any]) -> str:
    """ROOT_EVAL → FINALIZE | PLAN_REVIEW | DISPATCH | END."""
    if state.get("root_eval_route") == "fatal" or state.get("last_outcome") == "fatal":
        return END
    if state.get("root_eval_route") == "dispatch":
        return DISPATCH
    # Plan mode: route to plan review instead of goal completion.
    if state.get("interaction_mode") == "plan":
        logger.debug("[routing] route_after_root_eval → plan_review (plan mode)")
        return PLAN_REVIEW
    return FINALIZE


def route_after_wired_subagent(state: dict[str, Any]) -> str:
    """Intake-only invoke → finalize or clarification (planner handoff removed)."""
    if state.get("last_outcome") == "fatal":
        logger.debug("[routing] route_after_wired_subagent → END (fatal)")
        return END
    if _pending_clarification(state):
        logger.debug("[routing] route_after_wired_subagent → await_user")
        return AWAIT_USER
    logger.debug("[routing] route_after_wired_subagent → finalize")
    return FINALIZE


def route_after_execute(state: dict[str, Any]) -> str:
    """Stop on execute fatal; otherwise record progress then reconcile."""
    if _pending_clarification(state):
        logger.debug("[routing] route_after_execute → await_user")
        return AWAIT_USER
    if state.get("last_outcome") == "fatal":
        logger.debug("[routing] route_after_execute → END (fatal)")
        return END
    logger.debug("[routing] route_after_execute → record_progress")
    return RECORD_PROGRESS


def route_after_record_iteration(state: dict[str, Any]) -> str:
    """After record: RECONCILE, or FINALIZE for terminal one-shot fallbacks."""
    after = state.get("after_record_route")
    if after in ("goal_completion", FINALIZE):
        return FINALIZE
    if state.get("last_outcome") == "fatal":
        return END
    return RECONCILE


def route_after_plan_review(state: dict[str, Any]) -> str:
    """Plan review → FINALIZE (approve/reject) or AWAIT_USER (pending/refine).

    On approve, ``handle_plan_mode_review_answer`` set ``plan_approved_follow_on``
    and stashed a follow-on exec signal on ``ctx.scratch.follow_on_exec``. The
    plan-mode goal finalizes (its root already completed during exploration);
    the finalize node attaches the follow-on signal to the ``completed`` event
    so the daemon enqueues a fresh exec goal carrying the approved plan.
    Reject finalizes the current goal without a follow-on. Refine re-emits the
    pending clarification so the user can provide more instruction. On a fresh
    plan review the pending clarification is still set → AWAIT_USER.
    """
    if state.get("plan_approved_follow_on"):
        logger.debug(
            "[routing] route_after_plan_review → finalize (plan approved; exec goal follows)"
        )
        return FINALIZE
    if state.get("plan_rejected_terminal"):
        logger.debug("[routing] route_after_plan_review → finalize (plan rejected)")
        return FINALIZE
    if _pending_clarification(state):
        logger.debug("[routing] route_after_plan_review → await_user")
        return AWAIT_USER
    logger.debug("[routing] route_after_plan_review → END (no pending, no approve)")
    return END


def route_after_clarification(state: dict[str, Any]) -> str:
    """Return to originating station, FINALIZE on plan-mode approve, or END on defer."""
    if state.get("last_outcome") == "deferred":
        return END
    from soothe.sloop.clarification.origins import (
        ORIGIN_PLAN_MODE_REVIEW,
        resume_node_for_clarification_origin,
    )

    origin = state.get("last_clarification_origin")
    # Plan-mode review answers route to PLAN_REVIEW for action-specific
    # processing. Approve and Reject then finalize; Refine re-emits the pending
    # clarification and routes back to AWAIT_USER.
    if origin == ORIGIN_PLAN_MODE_REVIEW:
        if state.get("plan_approved_follow_on"):
            logger.debug(
                "[routing] route_after_clarification → finalize (plan approved; exec goal follows)"
            )
            return FINALIZE
        # Route to PLAN_REVIEW so the action can be processed.
        pending = state.get("pending_clarification")
        if pending is not None:
            logger.debug("[routing] route_after_clarification → plan_review (process plan action)")
            return PLAN_REVIEW
        logger.debug("[routing] route_after_clarification → END (no pending, no approve)")
        return END
    resume = resume_node_for_clarification_origin(origin)
    return resume if resume is not None else END
