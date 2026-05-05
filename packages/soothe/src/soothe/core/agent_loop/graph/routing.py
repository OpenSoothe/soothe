"""Conditional edges for the Loop Graph (RFC-220)."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END

from .state import PLAN_ROUTE_GOAL_DONE


def route_after_init(state: dict[str, Any]) -> str:
    """Branch to fast-path terminal or normal iteration flow."""
    if state.get("intent_route") == "fast_path":
        return END
    return "iteration_gate"


def route_after_iteration_gate(state: dict[str, Any]) -> str:
    """End graph after max-iteration terminal; otherwise begin iteration body."""
    if state.get("last_outcome") == "max_iterations":
        return END
    return "iteration_start"


def route_after_plan(state: dict[str, Any]) -> str:
    """Branch to goal completion synthesis vs execute pipeline."""
    if state.get("plan_route") == PLAN_ROUTE_GOAL_DONE:
        return "goal_completion"
    return "resolve_decision"


def route_after_assess(state: dict[str, Any]) -> str:
    """Branch from assess: done/skip-generate/continue-generate."""
    if state.get("plan_route") == PLAN_ROUTE_GOAL_DONE:
        return "goal_completion"
    if state.get("assess_route") == "skip_generate":
        return "resolve_decision"
    return "plan_pre_generate"


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
    if state.get("last_outcome") == "fatal":
        return END
    return "record_iteration"


def route_after_record_iteration(state: dict[str, Any]) -> str:
    """Continue outer iteration cycle or finish."""
    if state.get("last_outcome") == "continue":
        return "iteration_gate"
    return END
