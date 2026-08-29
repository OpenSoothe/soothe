"""Tests for RFC-226 record_iteration → goal_completion fast-exit routing."""

from soothe.sloop.orchestrator.routing import route_after_record_iteration


def test_terminal_bootstrap_routes_to_goal_completion() -> None:
    state = {"after_record_route": "finalize", "last_outcome": "continue"}
    assert route_after_record_iteration(state) == "finalize"


def test_continue_routes_to_reconcile_when_not_terminal() -> None:
    state = {"after_record_route": "", "last_outcome": "continue"}
    assert route_after_record_iteration(state) == "reconcile"


def test_missing_after_record_route_falls_through() -> None:
    state = {"last_outcome": "continue"}
    assert route_after_record_iteration(state) == "reconcile"


def test_fatal_outcome_routes_to_reconcile() -> None:
    """Fatal no longer short-circuits to END — route through RECONCILE →
    ROOT_EVAL so ``_try_auto_to_manual_fallback`` can attempt recovery."""
    state = {"last_outcome": "fatal"}
    assert route_after_record_iteration(state) == "reconcile"


def test_terminal_takes_precedence_over_non_continue_outcome() -> None:
    state = {"after_record_route": "finalize", "last_outcome": "fatal"}
    assert route_after_record_iteration(state) == "finalize"
