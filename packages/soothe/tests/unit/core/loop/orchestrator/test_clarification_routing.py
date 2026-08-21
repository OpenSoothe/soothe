"""Routing short-circuits + await_clarification edges (RFC-622, RFC-904)."""

from __future__ import annotations

from unittest.mock import MagicMock

from langgraph.graph import END

from soothe.sloop.orchestrator.builder import build_strange_loop_graph
from soothe.sloop.orchestrator.routing import (
    route_after_clarification,
    route_after_execute,
)


def test_await_clarification_node_present_in_graph() -> None:
    ctx = MagicMock()
    compiled = build_strange_loop_graph(ctx)
    names = set(compiled.get_graph().nodes)
    assert "await_user" in names
    assert "dispatch" in names
    assert "reconcile" in names
    assert "generate_plan" not in names
    assert "evaluate" not in names
    assert "analyze_gaps" not in names
    assert "assess" not in names


def test_route_after_execute_short_circuits_on_pending_clarification() -> None:
    assert route_after_execute({"pending_clarification": {"questions": ["q"]}}) == "await_user"


def test_route_after_execute_preserved_when_no_pending() -> None:
    assert route_after_execute({}) == "record_progress"
    assert route_after_execute({"last_outcome": "fatal"}) == END


def test_route_after_clarification_returns_to_origin_node() -> None:
    from soothe.sloop.clarification.origins import (
        ORIGIN_EXECUTE,
        ORIGIN_PLAN_EVALUATE,
        ORIGIN_PLAN_GENERATE,
        ORIGIN_PLAN_MODE_REVIEW,
        resume_node_for_clarification_origin,
    )

    assert (
        route_after_clarification({"last_clarification_origin": ORIGIN_EXECUTE}) == ORIGIN_EXECUTE
    )
    # Legacy plan origins resume at DISPATCH under the RFC-904 topology.
    assert resume_node_for_clarification_origin(ORIGIN_PLAN_GENERATE) == "dispatch"
    assert (
        route_after_clarification({"last_clarification_origin": ORIGIN_PLAN_GENERATE}) == "dispatch"
    )
    assert (
        route_after_clarification({"last_clarification_origin": ORIGIN_PLAN_EVALUATE}) == "dispatch"
    )
    assert route_after_clarification({"last_clarification_origin": "assess"}) == "dispatch"
    # Plan-mode review without approved plan or pending clarification → END (reject).
    assert route_after_clarification({"last_clarification_origin": ORIGIN_PLAN_MODE_REVIEW}) == END
    # Plan-mode review with approved plan → DISPATCH (grounding).
    assert (
        route_after_clarification(
            {
                "last_clarification_origin": ORIGIN_PLAN_MODE_REVIEW,
                "approved_plan_markdown": "# Plan",
            }
        )
        == "dispatch"
    )
    # Plan-mode review with pending clarification → PLAN_REVIEW (comment/regenerate).
    assert (
        route_after_clarification(
            {
                "last_clarification_origin": ORIGIN_PLAN_MODE_REVIEW,
                "pending_clarification": {"q": "a"},
            }
        )
        == "plan_review"
    )


def test_route_after_clarification_terminates_on_deferred_outcome() -> None:
    assert (
        route_after_clarification(
            {"last_outcome": "deferred", "last_clarification_origin": "execute"}
        )
        == END
    )


def test_route_after_clarification_terminates_when_origin_missing() -> None:
    assert route_after_clarification({}) == END


def test_route_after_clarification_terminates_on_invalid_origin() -> None:
    assert route_after_clarification({"last_clarification_origin": "garbage"}) == END
