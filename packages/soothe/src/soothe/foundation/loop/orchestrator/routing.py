"""Conditional edges for the Loop Graph (RFC-220, RFC-622, RFC-630)."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END

from soothe.foundation.loop.intention.models import IntakeLabel

from .state import PLAN_ROUTE_GOAL_DONE

logger = logging.getLogger(__name__)


def route_after_evidence_gather(state: dict[str, Any]) -> str:
    """IG-476: Route from bounded_evidence_gather based on fresh-loop detection.

    When evidence_gather_route is "plan_generate_skip_assess", shortcut directly
    to plan_generate with the synthetic assessment already set in scratch.
    Otherwise, proceed to plan_assess for normal assessment flow.
    """
    route = state.get("evidence_gather_route")
    if route == "plan_generate_skip_assess":
        logger.debug("[routing] route_after_evidence_gather → plan_generate (fresh-loop skip)")
        return "plan_generate"
    logger.debug("[routing] route_after_evidence_gather → plan_assess")
    return "plan_assess"


def _pending_clarification(state: dict[str, Any]) -> bool:
    """RFC-622: yield to ``await_clarification`` when a request is pending and
    the policy has not yet returned an answer.

    IG-462: ``await_clarification`` keeps ``pending_clarification`` set so the
    originating node can pair it with the answer on re-entry. We must not
    re-route those re-entries back into ``await_clarification`` — the answer
    being present is the signal that we're past the relay.
    """
    pending = state.get("pending_clarification")
    answer = state.get("pending_clarification_answer")
    result = bool(pending) and not answer
    logger.debug(
        "[routing] _pending_clarification: pending=%s, answer=%s, result=%s",
        bool(pending),
        answer,
        result,
    )
    return result


def route_by_intent(state: dict[str, Any]) -> str:
    """RFC-630: branch dispatch after init_or_resume by intake label.

    Continuation is checked first from the structural ``is_continuation`` flag
    set by ``init_or_resume`` (derived from checkpoint state, not the LLM
    label) — continuation turns always go to ``plan_assess``. Then matches the
    4-class intake label:

    - ``quiz``    → END (handled pre-graph; defensive duplicate)
    - ``trivial`` → ``resolve_decision`` (synth 1-step plan in scratch, no plan LLM)
    - ``simple``  → ``plan_generate`` (skip bounded_evidence_gather + plan_assess)
    - ``complex`` → ``bounded_evidence_gather`` (full existing spine, IG-476 intact)

    Falls back to ``bounded_evidence_gather`` (complex) when the label is
    missing — the fail-safe path runs the full pipeline.
    """
    if state.get("is_continuation"):
        logger.debug("[routing] route_by_intent → plan_assess (continuation overlay)")
        return "plan_assess"

    if state.get("intent_route") == "fast_path":
        logger.debug("[routing] route_by_intent → END (quiz fast-path)")
        return END

    label = state.get("intake_label")
    if label == IntakeLabel.TRIVIAL:
        logger.debug("[routing] route_by_intent → resolve_decision (trivial)")
        return "resolve_decision"
    if label == IntakeLabel.SIMPLE:
        logger.debug("[routing] route_by_intent → plan_generate (simple)")
        return "plan_generate"
    logger.debug("[routing] route_by_intent → bounded_evidence_gather (complex/default)")
    return "bounded_evidence_gather"


def route_after_init(state: dict[str, Any]) -> str:
    """Branch to fast-path terminal or normal iteration flow."""
    if state.get("intent_route") == "fast_path":
        return END
    return "iteration_gate"


def route_after_iteration_gate(state: dict[str, Any]) -> str:
    """End graph after max-iteration or rate-limit terminal; otherwise begin iteration body."""
    if state.get("last_outcome") in ("max_iterations", "rate_limited"):
        return END
    return "iteration_start"


def route_after_plan(state: dict[str, Any]) -> str:
    """Branch to goal completion synthesis vs execute pipeline."""
    if _pending_clarification(state):
        return "await_clarification"
    if state.get("plan_route") == PLAN_ROUTE_GOAL_DONE:
        return "goal_completion"
    return "resolve_decision"


def route_after_assess(state: dict[str, Any]) -> str:
    """Branch from assess: done/skip-generate/continue-generate."""
    if _pending_clarification(state):
        return "await_clarification"
    if state.get("plan_route") == PLAN_ROUTE_GOAL_DONE:
        return "goal_completion"
    if state.get("assess_route") == "skip_generate":
        return "resolve_decision"
    return "plan_generate"


def route_after_resolve_decision(state: dict[str, Any]) -> str:
    """Stop on planner fatal; otherwise validate evidence refs."""
    if state.get("last_outcome") == "fatal":
        return END
    return "validate_evidence_bindings"


def route_after_validate_evidence(state: dict[str, Any]) -> str:
    """Stop on validation fatal; otherwise CoreAgent execute."""
    if state.get("last_outcome") == "fatal":
        return END
    return "execute"


def route_after_execute(state: dict[str, Any]) -> str:
    """Stop on execute fatal; otherwise persist iteration."""
    if _pending_clarification(state):
        logger.info("[routing] route_after_execute → await_clarification")
        return "await_clarification"
    if state.get("last_outcome") == "fatal":
        logger.debug("[routing] route_after_execute → END (fatal)")
        return END
    # RFC-622 resume synthesis: scratch has no plan_result/decision so
    # record_iteration would emit fatal_error. The synthesized step has
    # already emitted step_completed and execute_steps advanced
    # state.iteration; skip straight to iteration_gate to start the next cycle.
    if state.get("resume_synth"):
        logger.info("[routing] route_after_execute → iteration_gate (resume synth)")
        return "iteration_gate"
    logger.debug("[routing] route_after_execute → record_iteration")
    return "record_iteration"


def route_after_record_iteration(state: dict[str, Any]) -> str:
    """RFC-226: terminal bootstrap fast-exit, then continue outer iteration cycle or finish."""
    if state.get("after_record_route") == "goal_completion":
        return "goal_completion"
    if state.get("last_outcome") == "continue":
        return "iteration_gate"
    return END


def route_after_clarification(state: dict[str, Any]) -> str:
    """RFC-622: return to originating node, or END on defer."""
    if state.get("last_outcome") == "deferred":
        return END
    origin = state.get("last_clarification_origin")
    if origin in ("execute", "plan_generate", "plan_assess"):
        return origin
    return END
