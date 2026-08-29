"""Tests for ROOT_EVAL conditional routing.

root_eval fatal outcomes (unresolved failed steps, action tree not green with
no ready steps, max eval rounds) must route to FINALIZE — not END — so the
goal produces a completion report from finished steps instead of silently
ending the stream.
"""

from __future__ import annotations

from soothe.sloop.orchestrator.routing import route_after_root_eval


def test_root_eval_fatal_routes_to_finalize() -> None:
    """Fatal root_eval (failed steps / not green / max rounds) → FINALIZE.

    Without this, the stream ends with turn_completed=False and the TUI shows
    "Stream ended unexpectedly" even though steps completed successfully.
    """
    assert route_after_root_eval({"root_eval_route": "fatal"}) == "finalize"


def test_root_eval_fatal_via_last_outcome_routes_to_finalize() -> None:
    assert route_after_root_eval({"last_outcome": "fatal"}) == "finalize"


def test_root_eval_dispatch_routes_to_dispatch() -> None:
    assert route_after_root_eval({"root_eval_route": "dispatch"}) == "dispatch"


def test_root_eval_finalize_routes_to_finalize() -> None:
    assert route_after_root_eval({"root_eval_route": "finalize"}) == "finalize"


def test_root_eval_default_routes_to_finalize() -> None:
    assert route_after_root_eval({}) == "finalize"


def test_root_eval_plan_mode_routes_to_plan_review() -> None:
    assert (
        route_after_root_eval({"interaction_mode": "plan", "root_eval_route": "finalize"})
        == "plan_review"
    )


def test_root_eval_plan_mode_takes_precedence_over_default() -> None:
    """Plan mode routes to PLAN_REVIEW even without explicit root_eval_route."""
    assert route_after_root_eval({"interaction_mode": "plan"}) == "plan_review"
