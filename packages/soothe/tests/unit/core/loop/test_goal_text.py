"""Tests for resolve_planning_goal (verbatim user submission)."""

from __future__ import annotations

from soothe.foundation.sloop.goal_text import resolve_planning_goal, resolve_user_request
from soothe.foundation.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
)
from soothe.foundation.sloop.state.schemas import LoopState


def test_resolve_planning_goal_prefers_goal_user_submission() -> None:
    state = LoopState(
        goal="using existing daemon. Run all tests",
        goal_user_submission="Run all Go and TypeScript client tests and fix all errors",
        thread_id="t",
        intent=IntentClassification(
            intake_label=IntakeLabel.COMPLEX,
            task_complexity=TaskComplexity.COMPLEX,
        ),
    )
    assert resolve_planning_goal(state) == (
        "Run all Go and TypeScript client tests and fix all errors"
    )


def test_resolve_planning_goal_falls_back_to_state_goal() -> None:
    state = LoopState(goal="raw user goal", thread_id="t")
    assert resolve_planning_goal(state) == "raw user goal"


def test_resolve_user_request_prefers_goal_user_submission() -> None:
    state = LoopState(
        goal="execution-only goal",
        goal_user_submission="verbatim user line",
        thread_id="t",
    )
    assert resolve_user_request(state) == "verbatim user line"


def test_resolve_user_request_falls_back_to_state_goal() -> None:
    state = LoopState(goal="raw user goal", thread_id="t")
    assert resolve_user_request(state) == "raw user goal"
