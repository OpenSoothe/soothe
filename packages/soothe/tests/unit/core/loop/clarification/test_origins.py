"""Unit tests for clarification verification-stage origin constants."""

from __future__ import annotations

from soothe.sloop.clarification.origins import (
    ACCEPTED_CLARIFICATION_ORIGINS,
    CLARIFICATION_ORIGINS,
    DEFAULT_FORCE_MANUAL_ORIGINS,
    ORIGIN_EXECUTE,
    ORIGIN_PLAN_EVALUATE,
    ORIGIN_PLAN_GENERATE,
    ORIGIN_PLANNER_SUBAGENT_REVIEW,
    STRANGELOOP_PLANNING_ORIGINS,
    resume_node_for_clarification_origin,
)


def test_clarification_origins_cover_all_stages() -> None:
    assert CLARIFICATION_ORIGINS == {
        ORIGIN_EXECUTE,
        ORIGIN_PLAN_GENERATE,
        ORIGIN_PLAN_EVALUATE,
        ORIGIN_PLANNER_SUBAGENT_REVIEW,
    }


def test_strange_loop_planning_origins_exclude_planner_subagent_review() -> None:
    assert ORIGIN_PLANNER_SUBAGENT_REVIEW not in STRANGELOOP_PLANNING_ORIGINS
    assert ORIGIN_EXECUTE not in STRANGELOOP_PLANNING_ORIGINS
    assert STRANGELOOP_PLANNING_ORIGINS == {
        ORIGIN_PLAN_GENERATE,
        ORIGIN_PLAN_EVALUATE,
    }


def test_default_force_manual_is_planner_subagent_review_only() -> None:
    assert DEFAULT_FORCE_MANUAL_ORIGINS == (ORIGIN_PLANNER_SUBAGENT_REVIEW,)


def test_resume_node_mapping() -> None:
    assert resume_node_for_clarification_origin(ORIGIN_EXECUTE) == ORIGIN_EXECUTE
    assert resume_node_for_clarification_origin(ORIGIN_PLAN_GENERATE) == ORIGIN_PLAN_GENERATE
    assert resume_node_for_clarification_origin(ORIGIN_PLAN_EVALUATE) == ORIGIN_PLAN_EVALUATE
    # Legacy assess / gap origins resume into evaluate (IG-672).
    assert resume_node_for_clarification_origin("assess") == ORIGIN_PLAN_EVALUATE
    assert resume_node_for_clarification_origin("analyze_gaps") == ORIGIN_PLAN_EVALUATE
    assert resume_node_for_clarification_origin("plan_assess") == ORIGIN_PLAN_EVALUATE
    assert resume_node_for_clarification_origin("plan_gap_analysis") == ORIGIN_PLAN_EVALUATE
    assert resume_node_for_clarification_origin(ORIGIN_PLANNER_SUBAGENT_REVIEW) == "delegate"
    assert resume_node_for_clarification_origin("not_a_stage") is None
    assert resume_node_for_clarification_origin(None) is None


def test_accepted_includes_legacy_origins() -> None:
    assert "plan_assess" in ACCEPTED_CLARIFICATION_ORIGINS
    assert "assess" in ACCEPTED_CLARIFICATION_ORIGINS
    assert "plan_assess" not in CLARIFICATION_ORIGINS
