"""Tests for the relay origin router (IG-775)."""

from __future__ import annotations

from soothe.sloop.clarification.origins import (
    ORIGIN_EXECUTE,
    ORIGIN_PLAN_MODE_REVIEW,
    ORIGIN_RAIL_PAUSE,
    ORIGIN_TOOL_APPROVAL,
)
from soothe.sloop.orchestrator.stations import EXECUTE, PLAN_REVIEW
from soothe.sloop.relay.router import (
    pause_mode_for_origin,
    resume_node_for_clarification_origin,
)


class TestResumeNodeMapping:
    def test_execute_resumes_at_execute(self) -> None:
        assert resume_node_for_clarification_origin(ORIGIN_EXECUTE) == EXECUTE

    def test_tool_approval_resumes_at_execute(self) -> None:
        assert resume_node_for_clarification_origin(ORIGIN_TOOL_APPROVAL) == EXECUTE

    def test_plan_mode_review_resumes_at_plan_review(self) -> None:
        assert resume_node_for_clarification_origin(ORIGIN_PLAN_MODE_REVIEW) == PLAN_REVIEW

    def test_rail_pause_is_host_only_no_resume(self) -> None:
        assert resume_node_for_clarification_origin(ORIGIN_RAIL_PAUSE) is None

    def test_unknown_origin_returns_none(self) -> None:
        assert resume_node_for_clarification_origin("nope") is None

    def test_none_origin_returns_none(self) -> None:
        assert resume_node_for_clarification_origin(None) is None


class TestPauseMode:
    def test_execute_defaults_interactive(self) -> None:
        assert pause_mode_for_origin(ORIGIN_EXECUTE) == "interactive"

    def test_tool_approval_defaults_interactive(self) -> None:
        assert pause_mode_for_origin(ORIGIN_TOOL_APPROVAL) == "interactive"

    def test_plan_mode_review_defaults_interactive(self) -> None:
        assert pause_mode_for_origin(ORIGIN_PLAN_MODE_REVIEW) == "interactive"

    def test_rail_pause_is_hard_defer(self) -> None:
        assert pause_mode_for_origin(ORIGIN_RAIL_PAUSE) == "hard_defer"
