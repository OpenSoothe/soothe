"""Conditional edges for the Loop Graph (RFC-904, RFC-622)."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END

from soothe.sloop.intention.models import IntakeLabel

from .stations import (
    AWAIT_USER,
    DELEGATE,
    DISPATCH,
    EXECUTE,
    FINALIZE,
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
    """Branch after enter_loop: chitchat END, wired delegate, or DISPATCH."""
    new_goal_created = state.get("new_goal_created", False)
    label = state.get("intake_label")

    if new_goal_created and label == IntakeLabel.CHITCHAT:
        logger.warning(
            "[routing] chitchat blocked by new_goal_created constraint; "
            "forcing dispatch (structural override)"
        )
        label = IntakeLabel.COMPLEX

    if state.get("intent_route") == "fast_path":
        if new_goal_created:
            logger.warning(
                "[routing] intent_route fast_path blocked by new_goal_created; forcing dispatch"
            )
            return DISPATCH
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


# Historical name used by tests and docs.
route_by_intent = route_after_preprocess


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
    """ROOT_EVAL → FINALIZE | DISPATCH (gap re-dispatch)."""
    if state.get("root_eval_route") == "dispatch":
        return DISPATCH
    return FINALIZE


def route_after_wired_subagent(state: dict[str, Any]) -> str:
    """Intake-only invoke → finalize, clarification, or DISPATCH handoff."""
    if state.get("last_outcome") == "fatal":
        logger.debug("[routing] route_after_wired_subagent → END (fatal)")
        return END
    if _pending_clarification(state):
        logger.debug("[routing] route_after_wired_subagent → await_user")
        return AWAIT_USER
    if state.get("planner_implement_handoff"):
        logger.debug("[routing] route_after_wired_subagent → dispatch (handoff)")
        return DISPATCH
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


def route_after_clarification(state: dict[str, Any]) -> str:
    """Return to originating station, or END on defer."""
    if state.get("last_outcome") == "deferred":
        return END
    from soothe.sloop.clarification.origins import resume_node_for_clarification_origin

    resume = resume_node_for_clarification_origin(state.get("last_clarification_origin"))
    # Legacy plan stations map to DISPATCH under the decompose topology.
    if resume in ("generate_plan", "evaluate", "gather_evidence", "commit_plan", "check_limits"):
        return DISPATCH
    return resume if resume is not None else END


# --- Legacy routers (plan spine removed from live graph; kept for unit tests) ---


def route_after_evidence_gather(state: dict[str, Any]) -> str:
    """Legacy gather_evidence router (plan spine removed from live graph)."""
    route = state.get("evidence_gather_route")
    if route == "keep_plan":
        return "commit_plan"
    if route == "plan_generate_skip_evaluate":
        return "generate_plan"
    return "evaluate"


def route_after_iteration_gate(state: dict[str, Any]) -> str:
    """Legacy check_limits router."""
    if state.get("last_outcome") in ("max_iterations", "rate_limited"):
        return END
    return "gather_evidence"


def route_after_plan(state: dict[str, Any]) -> str:
    """Legacy generate_plan router."""
    if _pending_clarification(state):
        return AWAIT_USER
    if state.get("last_outcome") == "fatal":
        return "commit_plan"
    if state.get("plan_route") == "goal_done":
        return FINALIZE
    if state.get("assess_route") == "continue_generate":
        return "generate_plan"
    return "commit_plan"


def route_after_evaluate(state: dict[str, Any]) -> str:
    """Legacy evaluate router."""
    if _pending_clarification(state):
        return AWAIT_USER
    if state.get("plan_route") == "goal_done":
        return FINALIZE
    if state.get("assess_route") == "skip_generate":
        return "commit_plan"
    return "generate_plan"


def route_after_commit(state: dict[str, Any]) -> str:
    """Legacy commit_plan router."""
    if state.get("last_outcome") == "fatal":
        return END
    return EXECUTE
