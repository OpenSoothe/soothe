"""Routing short-circuits + await_clarification edges (RFC-622)."""

from __future__ import annotations

from unittest.mock import MagicMock

from langgraph.graph import END

from soothe.foundation.loop.orchestrator.builder import build_strange_loop_graph
from soothe.foundation.loop.orchestrator.routing import (
    route_after_assess,
    route_after_clarification,
    route_after_execute,
    route_after_plan,
)


def test_await_clarification_node_present_in_graph() -> None:
    ctx = MagicMock()
    compiled = build_strange_loop_graph(ctx)
    names = set(compiled.get_graph().nodes)
    assert "await_clarification" in names


def test_route_after_execute_short_circuits_on_pending_clarification() -> None:
    assert (
        route_after_execute({"pending_clarification": {"questions": ["q"]}})
        == "await_clarification"
    )


def test_route_after_plan_short_circuits_on_pending_clarification() -> None:
    assert (
        route_after_plan({"pending_clarification": {"questions": ["q"]}}) == "await_clarification"
    )


def test_route_after_assess_short_circuits_on_pending_clarification() -> None:
    assert (
        route_after_assess({"pending_clarification": {"questions": ["q"]}}) == "await_clarification"
    )


def test_route_after_execute_preserved_when_no_pending() -> None:
    assert route_after_execute({}) == "record_iteration"
    assert route_after_execute({"last_outcome": "fatal"}) == END


def test_route_after_clarification_returns_to_origin_node() -> None:
    assert route_after_clarification({"last_clarification_origin": "execute"}) == "execute"
    assert (
        route_after_clarification({"last_clarification_origin": "plan_generate"}) == "plan_generate"
    )
    assert route_after_clarification({"last_clarification_origin": "plan_assess"}) == "plan_assess"


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
