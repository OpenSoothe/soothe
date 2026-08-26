"""Unit tests for clarification origin constants."""

from __future__ import annotations

from soothe.sloop.clarification.origins import (
    CLARIFICATION_ORIGIN_RESUME_NODE,
    CLARIFICATION_ORIGINS,
    DEFAULT_FORCE_MANUAL_ORIGINS,
    ORIGIN_EXECUTE,
    ORIGIN_PLAN_MODE_REVIEW,
    ORIGIN_RAIL_PAUSE,
    ORIGIN_TOOL_APPROVAL,
    resume_node_for_clarification_origin,
)


def test_clarification_origins_are_live_only() -> None:
    assert CLARIFICATION_ORIGINS == {
        ORIGIN_EXECUTE,
        ORIGIN_PLAN_MODE_REVIEW,
        ORIGIN_RAIL_PAUSE,
        ORIGIN_TOOL_APPROVAL,
    }


def test_default_force_manual_includes_plan_review_only() -> None:
    assert ORIGIN_PLAN_MODE_REVIEW in DEFAULT_FORCE_MANUAL_ORIGINS
    assert ORIGIN_TOOL_APPROVAL not in DEFAULT_FORCE_MANUAL_ORIGINS


def test_resume_node_mapping() -> None:
    assert resume_node_for_clarification_origin(ORIGIN_EXECUTE) == ORIGIN_EXECUTE
    assert resume_node_for_clarification_origin(ORIGIN_PLAN_MODE_REVIEW) == "plan_review"
    assert resume_node_for_clarification_origin(ORIGIN_TOOL_APPROVAL) == ORIGIN_EXECUTE
    assert resume_node_for_clarification_origin(ORIGIN_RAIL_PAUSE) is None
    assert resume_node_for_clarification_origin("not_a_stage") is None
    assert resume_node_for_clarification_origin(None) is None


def test_rail_pause_not_force_manual_by_default() -> None:
    assert ORIGIN_RAIL_PAUSE not in DEFAULT_FORCE_MANUAL_ORIGINS


def test_tool_approval_not_force_manual_by_default() -> None:
    """tool_approval is auto-evaluated by veritas in auto mode by default."""
    assert ORIGIN_TOOL_APPROVAL not in DEFAULT_FORCE_MANUAL_ORIGINS


def test_resume_node_dict_keys_match_origins() -> None:
    assert set(CLARIFICATION_ORIGIN_RESUME_NODE) == CLARIFICATION_ORIGINS - {ORIGIN_RAIL_PAUSE}
