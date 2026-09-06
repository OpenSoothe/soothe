"""Conditional edges for the Loop Graph."""

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
    """True when the relay inbox has a head entry with no answer built yet.

    Reads the `relay_state` channel: inbox non-empty and answer slot `None`.
    """
    relay_state = state.get("relay_state")
    if not isinstance(relay_state, dict):
        return False
    inbox = relay_state.get("inbox")
    if not isinstance(inbox, list) or not inbox:
        return False
    return relay_state.get("answer") is None


def route_after_preprocess(state: dict[str, Any]) -> str:
    """Branch after enter_loop: chitchat END, wired delegate, or DISPATCH."""
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
    """DISPATCH → EXECUTE | ROOT_EVAL | END (budget terminal)."""
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
    """ROOT_EVAL → FINALIZE | PLAN_REVIEW | DISPATCH.

    Fatal outcomes route to FINALIZE so the goal produces a completion
    report from finished steps instead of silently ending the stream.
    """
    if state.get("root_eval_route") == "fatal" or state.get("last_outcome") == "fatal":
        logger.debug("[routing] route_after_root_eval → finalize (root_eval fatal)")
        return FINALIZE
    if state.get("root_eval_route") == "dispatch":
        return DISPATCH
    if state.get("interaction_mode") == "plan":
        logger.debug("[routing] route_after_root_eval → plan_review (plan mode)")
        return PLAN_REVIEW
    return FINALIZE


def route_after_wired_subagent(state: dict[str, Any]) -> str:
    """Intake-only invoke → finalize or clarification."""
    if state.get("last_outcome") == "fatal":
        logger.debug("[routing] route_after_wired_subagent → END (fatal)")
        return END
    if _pending_clarification(state):
        logger.debug("[routing] route_after_wired_subagent → await_user")
        return AWAIT_USER
    logger.debug("[routing] route_after_wired_subagent → finalize")
    return FINALIZE


def route_after_execute(state: dict[str, Any]) -> str:
    """EXECUTE → RECORD_PROGRESS | AWAIT_USER.

    Fatal errors flow through to ROOT_EVAL for recovery / completion report.
    """
    if _pending_clarification(state):
        logger.debug("[routing] route_after_execute → await_user")
        return AWAIT_USER
    logger.debug("[routing] route_after_execute → record_progress")
    return RECORD_PROGRESS


def route_after_record_iteration(state: dict[str, Any]) -> str:
    """After record: RECONCILE, or FINALIZE for terminal one-shot fallbacks."""
    after = state.get("after_record_route")
    if after in ("goal_completion", FINALIZE):
        return FINALIZE
    return RECONCILE


def route_after_plan_review(state: dict[str, Any]) -> str:
    """Plan review → FINALIZE (approve/reject) or AWAIT_USER (pending/refine)."""
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
    """Return to origin station, FINALIZE on plan approve, or END on defer."""
    if state.get("last_outcome") == "deferred":
        return END
    from soothe.sloop.clarification.origins import ORIGIN_PLAN_MODE_REVIEW
    from soothe.sloop.relay.router import resume_node_for_clarification_origin

    origin = _active_origin(state)
    if origin == ORIGIN_PLAN_MODE_REVIEW:
        if state.get("plan_approved_follow_on"):
            logger.debug(
                "[routing] route_after_clarification → finalize (plan approved; exec goal follows)"
            )
            return FINALIZE
        if _pending_clarification(state):
            logger.debug("[routing] route_after_clarification → plan_review (process plan action)")
            return PLAN_REVIEW
        logger.debug("[routing] route_after_clarification → END (no pending, no approve)")
        return END
    resume = resume_node_for_clarification_origin(origin)
    return resume if resume is not None else END


def _active_origin(state: dict[str, Any]) -> str | None:
    """Read the active clarification origin from the `relay_state` channel."""
    relay_state = state.get("relay_state")
    if not isinstance(relay_state, dict):
        return None
    origin = relay_state.get("active_origin")
    if origin:
        return str(origin)
    inbox = relay_state.get("inbox")
    if isinstance(inbox, list) and inbox:
        head = inbox[0]
        if isinstance(head, dict):
            request = head.get("request")
            if isinstance(request, dict):
                return request.get("origin_node")
    return None
