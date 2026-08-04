"""Tests for resolve_planning_goal (verbatim user submission)."""

from __future__ import annotations

from types import SimpleNamespace

from soothe.sloop.goal_text import (
    apply_clarification_resume_goal_text,
    resolve_clarification_resume_ce_goal,
    resolve_interrupt_resume_ce_goal,
    resolve_planning_goal,
    resolve_user_request,
)
from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
)
from soothe.sloop.state.schemas import LoopState


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


def test_resolve_clarification_resume_ce_goal_prefers_loop_assigned_active() -> None:
    match = SimpleNamespace(
        id="g-match",
        status="active",
        assigned_loop_id="loop-1",
        description="optimize deps",
        updated_at=2,
    )
    other = SimpleNamespace(
        id="g-other",
        status="active",
        assigned_loop_id="loop-2",
        description="other",
        updated_at=3,
    )
    ce = SimpleNamespace(get_all_goals=lambda: [other, match])
    assert resolve_clarification_resume_ce_goal(ce, loop_id="loop-1") is match


def test_resolve_clarification_resume_ce_goal_returns_none_without_active() -> None:
    pending = SimpleNamespace(
        id="g1",
        status="pending",
        assigned_loop_id="loop-1",
        description="x",
        updated_at=1,
    )
    ce = SimpleNamespace(get_all_goals=lambda: [pending])
    assert resolve_clarification_resume_ce_goal(ce, loop_id="loop-1") is None


def test_apply_clarification_resume_goal_text_overwrites_answer() -> None:
    state = LoopState(goal="Approve", goal_user_submission="Approve", thread_id="t")
    ce_goal = SimpleNamespace(description="generate a plan to optimize submodules")
    original = apply_clarification_resume_goal_text(state, ce_goal)
    assert original == "generate a plan to optimize submodules"
    assert state.goal == original
    assert state.goal_user_submission is None
    assert resolve_user_request(state) == original


def test_resolve_interrupt_resume_prefers_active_over_cancelled() -> None:
    active = SimpleNamespace(
        id="g-active",
        status="active",
        assigned_loop_id="loop-1",
        description="implement statemachine",
        updated_at=1,
    )
    cancelled = SimpleNamespace(
        id="g-old",
        status="cancelled",
        assigned_loop_id="loop-1",
        description="old attempt",
        updated_at=9,
    )
    ce = SimpleNamespace(get_all_goals=lambda: [cancelled, active])
    assert resolve_interrupt_resume_ce_goal(ce, loop_id="loop-1") is active


def test_resolve_interrupt_resume_finds_suspended_or_cancelled() -> None:
    suspended = SimpleNamespace(
        id="g-susp",
        status="suspended",
        assigned_loop_id="loop-1",
        description="partial work",
        updated_at=2,
    )
    ce = SimpleNamespace(get_all_goals=lambda: [suspended])
    assert resolve_interrupt_resume_ce_goal(ce, loop_id="loop-1") is suspended

    cancelled = SimpleNamespace(
        id="g-can",
        status="cancelled",
        assigned_loop_id="loop-1",
        description="legacy cancel",
        updated_at=3,
    )
    ce2 = SimpleNamespace(get_all_goals=lambda: [cancelled])
    assert resolve_interrupt_resume_ce_goal(ce2, loop_id="loop-1") is cancelled
    # Clarification path still requires active.
    assert resolve_clarification_resume_ce_goal(ce2, loop_id="loop-1") is None
