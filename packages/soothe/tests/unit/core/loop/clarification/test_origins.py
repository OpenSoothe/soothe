"""Unit tests for clarification verification-stage origin constants."""

from __future__ import annotations

from soothe.sloop.clarification.origins import (
    ACCEPTED_CLARIFICATION_ORIGINS,
    CLARIFICATION_ORIGINS,
    DEFAULT_FORCE_MANUAL_ORIGINS,
    ORIGIN_EXECUTE,
    ORIGIN_PLAN_EVALUATE,
    ORIGIN_PLAN_GENERATE,
    ORIGIN_PLAN_MODE_REVIEW,
    ORIGIN_RAIL_PAUSE,
    STRANGELOOP_PLANNING_ORIGINS,
    resume_node_for_clarification_origin,
)


def test_clarification_origins_are_live_only() -> None:
    assert CLARIFICATION_ORIGINS == {
        ORIGIN_EXECUTE,
        ORIGIN_PLAN_MODE_REVIEW,
        ORIGIN_RAIL_PAUSE,
    }


def test_strange_loop_planning_origins_are_legacy_plan_spine() -> None:
    assert ORIGIN_PLAN_MODE_REVIEW not in STRANGELOOP_PLANNING_ORIGINS
    assert ORIGIN_EXECUTE not in STRANGELOOP_PLANNING_ORIGINS
    assert STRANGELOOP_PLANNING_ORIGINS == {
        ORIGIN_PLAN_GENERATE,
        ORIGIN_PLAN_EVALUATE,
        "planner_subagent_review",  # legacy checkpoint resume compat
        "plan_generate",
        "plan_assess",
        "plan_gap_analysis",
        "assess",
        "analyze_gaps",
    }


def test_default_force_manual_is_planner_subagent_review_only() -> None:
    assert DEFAULT_FORCE_MANUAL_ORIGINS == (ORIGIN_PLAN_MODE_REVIEW,)


def test_resume_node_mapping() -> None:
    assert resume_node_for_clarification_origin(ORIGIN_EXECUTE) == ORIGIN_EXECUTE
    # Plan-spine stations are gone; legacy origins resume at DISPATCH.
    assert resume_node_for_clarification_origin(ORIGIN_PLAN_GENERATE) == "dispatch"
    assert resume_node_for_clarification_origin(ORIGIN_PLAN_EVALUATE) == "dispatch"
    assert resume_node_for_clarification_origin("assess") == "dispatch"
    assert resume_node_for_clarification_origin("analyze_gaps") == "dispatch"
    assert resume_node_for_clarification_origin("plan_assess") == "dispatch"
    assert resume_node_for_clarification_origin("plan_gap_analysis") == "dispatch"
    assert resume_node_for_clarification_origin(ORIGIN_PLAN_MODE_REVIEW) == "delegate"
    assert resume_node_for_clarification_origin(ORIGIN_RAIL_PAUSE) is None
    assert resume_node_for_clarification_origin("not_a_stage") is None
    assert resume_node_for_clarification_origin(None) is None


def test_rail_pause_not_force_manual_by_default() -> None:
    assert ORIGIN_RAIL_PAUSE not in DEFAULT_FORCE_MANUAL_ORIGINS
    assert ORIGIN_RAIL_PAUSE not in STRANGELOOP_PLANNING_ORIGINS


def test_accepted_includes_legacy_origins() -> None:
    assert "plan_assess" in ACCEPTED_CLARIFICATION_ORIGINS
    assert "assess" in ACCEPTED_CLARIFICATION_ORIGINS
    assert ORIGIN_PLAN_GENERATE in ACCEPTED_CLARIFICATION_ORIGINS
    assert ORIGIN_PLAN_GENERATE not in CLARIFICATION_ORIGINS
    assert "plan_assess" not in CLARIFICATION_ORIGINS
