"""Tests for resolve_planning_goal (Pass 2 normalized goal text)."""

from __future__ import annotations

from soothe.foundation.sloop.goal_text import resolve_planning_goal
from soothe.foundation.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
)
from soothe.foundation.sloop.state.schemas import LoopState


def test_resolve_planning_goal_prefers_pass2_description() -> None:
    state = LoopState(
        goal="using existing daemon. Run all tests",
        thread_id="t",
        intent=IntentClassification(
            intake_label=IntakeLabel.COMPLEX,
            task_complexity=TaskComplexity.COMPLEX,
            goal_description="Run all Go and TypeScript client tests and fix all errors",
        ),
    )
    assert resolve_planning_goal(state) == (
        "Run all Go and TypeScript client tests and fix all errors"
    )


def test_resolve_planning_goal_falls_back_to_state_goal() -> None:
    state = LoopState(goal="raw user goal", thread_id="t")
    assert resolve_planning_goal(state) == "raw user goal"
