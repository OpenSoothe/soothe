"""Tests for RFC-226 record_iteration → goal_completion fast-exit routing."""

from langgraph.graph import END

from soothe.core.loop.orchestrator.routing import route_after_record_iteration


def test_terminal_bootstrap_routes_to_goal_completion() -> None:
    state = {"after_record_route": "goal_completion", "last_outcome": "continue"}
    assert route_after_record_iteration(state) == "goal_completion"


def test_continue_routes_to_iteration_gate_when_not_terminal() -> None:
    state = {"after_record_route": "", "last_outcome": "continue"}
    assert route_after_record_iteration(state) == "iteration_gate"


def test_missing_after_record_route_falls_through() -> None:
    state = {"last_outcome": "continue"}
    assert route_after_record_iteration(state) == "iteration_gate"


def test_non_continue_outcome_returns_end() -> None:
    state = {"last_outcome": "fatal"}
    assert route_after_record_iteration(state) == END


def test_terminal_takes_precedence_over_non_continue_outcome() -> None:
    # If, somehow, record_iteration set both terminal and a non-continue outcome,
    # the terminal fast-exit wins (correctness > defensive routing).
    state = {"after_record_route": "goal_completion", "last_outcome": "fatal"}
    assert route_after_record_iteration(state) == "goal_completion"
