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


def _relay_pending(origin: str = "execute") -> dict:
    """relay_state with an unanswered head entry."""
    return {"relay_state": {"inbox": [{"request": {"origin_node": origin}}], "answer": None}}


def _relay_active(origin: str) -> dict:
    return {"relay_state": {"active_origin": origin}}


def test_route_after_execute_short_circuits_on_pending_clarification() -> None:
    assert route_after_execute(_relay_pending()) == "await_user"


def test_route_after_execute_preserved_when_no_pending() -> None:
    assert route_after_execute({}) == "record_progress"
    # Fatal no longer short-circuits to END — route through RECORD_PROGRESS →
    # RECONCILE → ROOT_EVAL for auto-recovery and completion report.
    assert route_after_execute({"last_outcome": "fatal"}) == "record_progress"


def test_route_after_clarification_returns_to_origin_node() -> None:
    from soothe.sloop.clarification.origins import (
        ORIGIN_EXECUTE,
        ORIGIN_PLAN_MODE_REVIEW,
        ORIGIN_TOOL_APPROVAL,
    )

    assert route_after_clarification(_relay_active(ORIGIN_EXECUTE)) == ORIGIN_EXECUTE
    assert route_after_clarification(_relay_active(ORIGIN_TOOL_APPROVAL)) == ORIGIN_EXECUTE
    # Plan-mode review without an action or pending clarification → END.
    assert route_after_clarification(_relay_active(ORIGIN_PLAN_MODE_REVIEW)) == END
    # Plan-mode review with pending clarification → PLAN_REVIEW to process the
    # selected action.
    assert route_after_clarification(_relay_pending(ORIGIN_PLAN_MODE_REVIEW)) == "plan_review"


def test_route_after_clarification_terminates_on_deferred_outcome() -> None:
    assert (
        route_after_clarification({"last_outcome": "deferred", **_relay_active("execute")}) == END
    )


def test_route_after_clarification_terminates_when_origin_missing() -> None:
    assert route_after_clarification({}) == END


def test_route_after_clarification_terminates_on_invalid_origin() -> None:
    assert route_after_clarification(_relay_active("garbage")) == END


def test_route_after_plan_review_routes_to_finalize_on_follow_on() -> None:
    """Plan-mode approve sets plan_approved_follow_on → FINALIZE.

    The plan-mode goal finalizes (its root already completed during
    exploration); the daemon enqueues a fresh exec goal carrying the approved
    plan. This replaces the old dead-root grounding path.
    """
    assert route_after_plan_review({"plan_approved_follow_on": True}) == "finalize"


def test_route_after_plan_review_routes_to_finalize_on_reject() -> None:
    assert route_after_plan_review({"plan_rejected_terminal": True}) == "finalize"


def test_route_after_clarification_finalizes_on_plan_mode_follow_on() -> None:
    """Plan-mode approve via clarification resume → FINALIZE (exec goal follows)."""
    from soothe.sloop.clarification.origins import ORIGIN_PLAN_MODE_REVIEW

    assert (
        route_after_clarification(
            {"plan_approved_follow_on": True, **_relay_active(ORIGIN_PLAN_MODE_REVIEW)}
        )
        == "finalize"
    )


def test_route_after_plan_review_routes_to_await_user_on_pending() -> None:
    """Fresh plan review has a pending clarification and no approved plan."""
    assert route_after_plan_review(_relay_pending("plan_mode_review")) == "await_user"


def test_route_after_plan_review_routes_to_end_on_no_pending_no_approve() -> None:
    """No pending and no approved plan → END (fallback; reject re-emits pending so this is not normally hit)."""
    assert route_after_plan_review({}) == END
    assert route_after_plan_review({"relay_state": {}}) == END


def test_route_after_clarification_refine_re_emits_to_await_user() -> None:
    """Refine re-emits pending → route_after_plan_review → AWAIT_USER.

    The full Refine flow:
    1. ``route_after_clarification`` sees pending (Refine answer) → PLAN_REVIEW
    2. ``handle_plan_mode_review_answer`` stores refinement text, re-emits
       pending (clearing the answer) via ``build_plan_mode_review_pending``.
    3. ``route_after_plan_review`` sees re-emitted pending → AWAIT_USER.

    The goal stays in plan mode for further refinement.
    """
    from soothe.sloop.clarification.origins import ORIGIN_PLAN_MODE_REVIEW

    # Step 1: Refine answer routes to PLAN_REVIEW for processing.
    assert route_after_clarification(_relay_pending(ORIGIN_PLAN_MODE_REVIEW)) == "plan_review"
    # Step 3: after handle_plan_mode_review_answer re-emits pending (answer
    # cleared), route_after_plan_review routes to AWAIT_USER.
    assert route_after_plan_review(_relay_pending("plan_mode_review")) == "await_user"


# --- relay_state routing path (IG-775) -----------------------------------------


def test_route_after_execute_short_circuits_on_relay_state_pending() -> None:
    """relay_state inbox with no answer routes to AWAIT_USER."""
    state = {"relay_state": {"inbox": [{"request": {}}], "answer": None}}
    assert route_after_execute(state) == "await_user"


def test_route_after_execute_preserved_when_relay_state_answered() -> None:
    """relay_state inbox with an answer does NOT short-circuit."""
    state = {"relay_state": {"inbox": [{"request": {}}], "answer": {"answers": ["y"]}}}
    assert route_after_execute(state) == "record_progress"


def test_route_after_execute_preserved_when_relay_state_empty_inbox() -> None:
    """Empty relay_state inbox falls through to record_progress."""
    assert route_after_execute({"relay_state": {"inbox": [], "answer": None}}) == "record_progress"


def test_route_after_clarification_reads_active_origin_from_relay_state() -> None:
    from soothe.sloop.clarification.origins import (
        ORIGIN_EXECUTE,
        ORIGIN_PLAN_MODE_REVIEW,
        ORIGIN_TOOL_APPROVAL,
    )

    assert (
        route_after_clarification({"relay_state": {"active_origin": ORIGIN_EXECUTE}})
        == ORIGIN_EXECUTE
    )
    assert (
        route_after_clarification({"relay_state": {"active_origin": ORIGIN_TOOL_APPROVAL}})
        == ORIGIN_EXECUTE
    )
    # Plan-mode review without pending → END.
    assert (
        route_after_clarification({"relay_state": {"active_origin": ORIGIN_PLAN_MODE_REVIEW}})
        == END
    )
    # Plan-mode review with relay inbox pending → PLAN_REVIEW.
    assert (
        route_after_clarification(
            {
                "relay_state": {
                    "active_origin": ORIGIN_PLAN_MODE_REVIEW,
                    "inbox": [{"request": {}}],
                    "answer": None,
                }
            }
        )
        == "plan_review"
    )


def test_route_after_plan_review_reads_relay_state_pending() -> None:
    assert (
        route_after_plan_review({"relay_state": {"inbox": [{"request": {}}], "answer": None}})
        == "await_user"
    )
