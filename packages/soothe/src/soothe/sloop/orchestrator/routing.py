"""Conditional edges for the Loop Graph (RFC-220, RFC-622, RFC-630, IG-663, IG-672)."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END

from soothe.sloop.intention.models import IntakeLabel

from .state import PLAN_ROUTE_GOAL_DONE
from .stations import (
    AWAIT_USER,
    BEGIN_ITERATION,
    CHECK_LIMITS,
    COMMIT_PLAN,
    DELEGATE,
    EVALUATE,
    EXECUTE,
    FINALIZE,
    GATHER_EVIDENCE,
    GENERATE_PLAN,
    RECORD_PROGRESS,
    VALIDATE_PLAN,
)

logger = logging.getLogger(__name__)


def route_after_evidence_gather(state: dict[str, Any]) -> str:
    """Route from gather_evidence based on fresh-loop / structural keep (IG-476, IG-671)."""
    route = state.get("evidence_gather_route")
    if route == "keep_plan":
        logger.info("[routing] route_after_evidence_gather → commit_plan (structural keep)")
        return COMMIT_PLAN
    if route == "plan_generate_skip_evaluate":
        logger.info("[routing] route_after_evidence_gather → generate_plan (fresh-loop skip)")
        return GENERATE_PLAN
    # IG-672: mid-goal path is always evaluate.
    logger.info("[routing] route_after_evidence_gather → evaluate")
    return EVALUATE


def _pending_clarification(state: dict[str, Any]) -> bool:
    """RFC-622: yield to ``await_user`` when a request is pending and unanswered."""
    pending = state.get("pending_clarification")
    answer = state.get("pending_clarification_answer")
    result = bool(pending) and not answer
    if result:
        logger.debug(
            "[routing] _pending_clarification: pending=%s, answer=%s, result=%s",
            bool(pending),
            answer,
            result,
        )
    return result


def route_after_preprocess(state: dict[str, Any]) -> str:
    """RFC-630 / IG-663: branch dispatch after enter_loop by intake.

    Priority (first match wins):

    1. ``intent_route == fast_path`` → END (chitchat)
    2. ``intent_route == wired_subagent`` → ``delegate``
    3. Continuation overlay from structural ``is_continuation``
    4. Fresh-loop labels (trivial+simple → trivial plan; complex → full spine)
    """
    new_goal_created = state.get("new_goal_created", False)
    label = state.get("intake_label")

    if new_goal_created and label == IntakeLabel.CHITCHAT:
        logger.warning(
            "[routing] chitchat blocked by new_goal_created constraint; "
            "forcing complex route (structural override)"
        )
        label = IntakeLabel.COMPLEX

    if state.get("intent_route") == "fast_path":
        if new_goal_created:
            logger.warning(
                "[routing] intent_route fast_path blocked by new_goal_created; "
                "forcing complex route"
            )
            return GATHER_EVIDENCE
        logger.info("[routing] route_after_preprocess → END (chitchat fast-path)")
        return END

    if state.get("intent_route") == "wired_subagent":
        logger.info("[routing] route_after_preprocess → delegate")
        return DELEGATE

    if state.get("is_continuation"):
        if label == IntakeLabel.SIMPLE:
            logger.info("[routing] route_after_preprocess → evaluate (continuation+simple)")
            return EVALUATE
        if label == IntakeLabel.COMPLEX or label is None:
            logger.info("[routing] route_after_preprocess → gather_evidence (continuation+complex)")
            return GATHER_EVIDENCE
        logger.info("[routing] route_after_preprocess → evaluate (continuation+trivial)")
        return EVALUATE

    if label == IntakeLabel.TRIVIAL or label == IntakeLabel.SIMPLE:
        logger.info(
            "[routing] route_after_preprocess → commit_plan (trivial pseudo-plan; label=%s)",
            label,
        )
        return COMMIT_PLAN  # build_trivial_plan → 1-step terminal
    logger.info("[routing] route_after_preprocess → gather_evidence (complex/default)")
    return GATHER_EVIDENCE  # full spine (default fallback)


# Historical name used by tests and docs.
route_by_intent = route_after_preprocess


def route_after_iteration_gate(state: dict[str, Any]) -> str:
    """End graph after max-iteration or rate-limit terminal; otherwise begin iteration."""
    if state.get("last_outcome") in ("max_iterations", "rate_limited"):
        return END
    return BEGIN_ITERATION


def route_after_plan(state: dict[str, Any]) -> str:
    """Branch to finalize vs execute pipeline after generate_plan."""
    if _pending_clarification(state):
        return AWAIT_USER
    if state.get("last_outcome") == "fatal":
        return COMMIT_PLAN
    if state.get("plan_route") == PLAN_ROUTE_GOAL_DONE:
        return FINALIZE
    if state.get("assess_route") == "continue_generate":
        logger.info("[routing] route_after_plan → generate_plan (continue_generate)")
        return GENERATE_PLAN
    return COMMIT_PLAN


def route_after_evaluate(state: dict[str, Any]) -> str:
    """Branch from evaluate: done / skip-generate / continue-generate."""
    if _pending_clarification(state):
        return AWAIT_USER
    if state.get("plan_route") == PLAN_ROUTE_GOAL_DONE:
        return FINALIZE
    if state.get("assess_route") == "skip_generate":
        return COMMIT_PLAN
    return GENERATE_PLAN


def route_after_resolve_decision(state: dict[str, Any]) -> str:
    """Stop on planner fatal; otherwise validate plan evidence refs."""
    if state.get("last_outcome") == "fatal":
        return END
    return VALIDATE_PLAN


def route_after_wired_subagent(state: dict[str, Any]) -> str:
    """Intake-only invoke → review, implement handoff, or finalize."""
    if state.get("last_outcome") == "fatal":
        logger.debug("[routing] route_after_wired_subagent → END (fatal)")
        return END
    if _pending_clarification(state):
        logger.info("[routing] route_after_wired_subagent → await_user")
        return AWAIT_USER
    if state.get("planner_implement_handoff"):
        logger.info("[routing] route_after_wired_subagent → generate_plan (approved plan handoff)")
        return GENERATE_PLAN
    logger.info("[routing] route_after_wired_subagent → finalize")
    return FINALIZE


def route_after_validate_evidence(state: dict[str, Any]) -> str:
    """Stop on validation fatal; otherwise CoreAgent execute."""
    if state.get("last_outcome") == "fatal":
        return END
    return EXECUTE


def route_after_execute(state: dict[str, Any]) -> str:
    """Stop on execute fatal; otherwise record progress."""
    if _pending_clarification(state):
        logger.info("[routing] route_after_execute → await_user")
        return AWAIT_USER
    if state.get("last_outcome") == "fatal":
        logger.debug("[routing] route_after_execute → END (fatal)")
        return END
    if state.get("resume_synth"):
        logger.info("[routing] route_after_execute → check_limits (resume synth)")
        return CHECK_LIMITS
    logger.info("[routing] route_after_execute → record_progress")
    return RECORD_PROGRESS


def route_after_record_iteration(state: dict[str, Any]) -> str:
    """Terminal bootstrap fast-exit, continue outer iteration, or finish."""
    after = state.get("after_record_route")
    if after in ("goal_completion", FINALIZE):
        return FINALIZE
    if state.get("last_outcome") == "continue":
        return CHECK_LIMITS
    return END


def route_after_clarification(state: dict[str, Any]) -> str:
    """RFC-622: return to originating station, or END on defer."""
    if state.get("last_outcome") == "deferred":
        return END
    from soothe.sloop.clarification.origins import resume_node_for_clarification_origin

    resume = resume_node_for_clarification_origin(state.get("last_clarification_origin"))
    return resume if resume is not None else END
