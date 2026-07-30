"""Routing short-circuits + await_clarification edges (RFC-622)."""

from __future__ import annotations

from unittest.mock import MagicMock

from langgraph.graph import END

from soothe.sloop.orchestrator.builder import build_strange_loop_graph
from soothe.sloop.orchestrator.routing import (
    route_after_assess,
    route_after_clarification,
    route_after_execute,
    route_after_plan,
)


def test_await_clarification_node_present_in_graph() -> None:
    ctx = MagicMock()
    compiled = build_strange_loop_graph(ctx)
    names = set(compiled.get_graph().nodes)
    assert "await_user" in names


def test_route_after_execute_short_circuits_on_pending_clarification() -> None:
    assert route_after_execute({"pending_clarification": {"questions": ["q"]}}) == "await_user"


def test_route_after_plan_short_circuits_on_pending_clarification() -> None:
    assert route_after_plan({"pending_clarification": {"questions": ["q"]}}) == "await_user"


def test_route_after_plan_loops_on_undersized_replan() -> None:
    assert route_after_plan({"assess_route": "continue_generate"}) == "generate_plan"


def test_route_after_plan_fatal_exits_before_undersized_replan() -> None:
    assert (
        route_after_plan({"last_outcome": "fatal", "assess_route": "continue_generate"})
        == "commit_plan"
    )


def test_route_after_plan_prefers_goal_done_over_replan() -> None:
    from soothe.sloop.orchestrator.state import PLAN_ROUTE_GOAL_DONE

    assert (
        route_after_plan({"plan_route": PLAN_ROUTE_GOAL_DONE, "assess_route": "continue_generate"})
        == "finalize"
    )


def test_route_after_assess_short_circuits_on_pending_clarification() -> None:
    assert route_after_assess({"pending_clarification": {"questions": ["q"]}}) == "await_user"


def test_route_after_execute_preserved_when_no_pending() -> None:
    assert route_after_execute({}) == "record_progress"
    assert route_after_execute({"last_outcome": "fatal"}) == END


def test_route_after_clarification_returns_to_origin_node() -> None:
    from soothe.sloop.clarification.origins import (
        ORIGIN_EXECUTE,
        ORIGIN_PLAN_ASSESS,
        ORIGIN_PLAN_GENERATE,
        ORIGIN_PLANNER_SUBAGENT_REVIEW,
    )

    assert (
        route_after_clarification({"last_clarification_origin": ORIGIN_EXECUTE}) == ORIGIN_EXECUTE
    )
    assert (
        route_after_clarification({"last_clarification_origin": ORIGIN_PLAN_GENERATE})
        == ORIGIN_PLAN_GENERATE
    )
    assert (
        route_after_clarification({"last_clarification_origin": ORIGIN_PLAN_ASSESS})
        == ORIGIN_PLAN_ASSESS
    )
    assert (
        route_after_clarification({"last_clarification_origin": ORIGIN_PLANNER_SUBAGENT_REVIEW})
        == "delegate"
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
