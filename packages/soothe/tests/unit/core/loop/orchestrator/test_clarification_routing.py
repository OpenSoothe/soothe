"""Routing short-circuits + await_clarification edges (RFC-622, RFC-904)."""

from __future__ import annotations

from unittest.mock import MagicMock

from langgraph.graph import END

from soothe.sloop.orchestrator.builder import build_strange_loop_graph
from soothe.sloop.orchestrator.routing import (
    route_after_clarification,
    route_after_execute,
    route_after_plan_review,
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
    # Plan-mode review without approved plan or pending clarification → END
    # (fallback; reject re-emits pending so this path is not normally hit).
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
    # Plan-mode review with pending clarification → PLAN_REVIEW (process the
    # reject answer: store refinement text, re-emit pending → AWAIT_USER).
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


def test_route_after_plan_review_routes_to_dispatch_on_approve() -> None:
    """Legacy approve (approved_plan_markdown set, no follow_on) → DISPATCH."""
    assert (
        route_after_plan_review({"approved_plan_markdown": "# Plan", "pending_clarification": None})
        == "dispatch"
    )
    # approved plan wins even if pending_clarification is somehow still set.
    assert (
        route_after_plan_review(
            {"approved_plan_markdown": "# Plan", "pending_clarification": {"q": "a"}}
        )
        == "dispatch"
    )


def test_route_after_plan_review_routes_to_finalize_on_follow_on() -> None:
    """Plan-mode approve sets plan_approved_follow_on → FINALIZE.

    The plan-mode goal finalizes (its root already completed during
    exploration); the daemon enqueues a fresh exec goal carrying the approved
    plan. This replaces the old dead-root grounding path.
    """
    assert (
        route_after_plan_review({"plan_approved_follow_on": True, "pending_clarification": None})
        == "finalize"
    )
    # follow_on wins over legacy approved_plan_markdown if both are set.
    assert (
        route_after_plan_review(
            {"plan_approved_follow_on": True, "approved_plan_markdown": "# Plan"}
        )
        == "finalize"
    )


def test_route_after_clarification_finalizes_on_plan_mode_follow_on() -> None:
    """Plan-mode approve via clarification resume → FINALIZE (exec goal follows)."""
    from soothe.sloop.clarification.origins import ORIGIN_PLAN_MODE_REVIEW

    assert (
        route_after_clarification(
            {
                "last_clarification_origin": ORIGIN_PLAN_MODE_REVIEW,
                "plan_approved_follow_on": True,
            }
        )
        == "finalize"
    )


def test_route_after_plan_review_routes_to_await_user_on_pending() -> None:
    """Fresh plan review has a pending clarification and no approved plan."""
    assert route_after_plan_review({"pending_clarification": {"q": "a"}}) == "await_user"


def test_route_after_plan_review_routes_to_end_on_no_pending_no_approve() -> None:
    """No pending and no approved plan → END (fallback; reject re-emits pending so this is not normally hit)."""
    assert route_after_plan_review({}) == END
    assert route_after_plan_review({"pending_clarification": None, "last_outcome": None}) == END


def test_route_after_clarification_reject_re_emits_to_await_user() -> None:
    """Reject re-emits pending → route_after_plan_review → AWAIT_USER (not END).

    The full reject flow:
    1. ``route_after_clarification`` sees pending (reject answer) → PLAN_REVIEW
    2. ``handle_plan_mode_review_answer`` stores refinement text, re-emits
       pending (clearing the answer) via ``build_plan_mode_review_pending``.
    3. ``route_after_plan_review`` sees re-emitted pending → AWAIT_USER.

    The goal stays in plan mode for further refinement; reject never terminates.
    """
    from soothe.sloop.clarification.origins import ORIGIN_PLAN_MODE_REVIEW

    # Step 1: reject answer routes to PLAN_REVIEW for processing.
    assert (
        route_after_clarification(
            {
                "last_clarification_origin": ORIGIN_PLAN_MODE_REVIEW,
                "pending_clarification": {"q": "a"},
            }
        )
        == "plan_review"
    )
    # Step 3: after handle_plan_mode_review_answer re-emits pending (answer
    # cleared), route_after_plan_review routes to AWAIT_USER.
    assert route_after_plan_review({"pending_clarification": {"q": "a"}}) == "await_user"
