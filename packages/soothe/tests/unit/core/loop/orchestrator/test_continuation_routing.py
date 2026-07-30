"""Tests for continuation routing helpers."""

from __future__ import annotations

from soothe.sloop.engine.continuation_context import build_continue_bootstrap_step_briefs
from soothe.sloop.orchestrator.continuation_routing import (
    bootstrap_terminal_after_execute,
)
from soothe.sloop.stages.plan.assess import (
    build_continue_loop_bootstrap_plan,
)


def test_bootstrap_uses_user_goal() -> None:
    briefs = build_continue_bootstrap_step_briefs(user_goal="create git commit")
    assert "create git commit" in briefs.full_description
    assert briefs.description == "create git commit"


def test_bootstrap_terminal_after_execute_for_follow_up_goal() -> None:
    assert bootstrap_terminal_after_execute(raw_user_goal="create git commit") is True


def test_bootstrap_terminal_after_execute_respects_multi_phase() -> None:
    assert (
        bootstrap_terminal_after_execute(
            raw_user_goal="create git commit",
            multi_phase=True,
        )
        is False
    )


def test_build_bootstrap_plan_terminal_auto_from_intent() -> None:
    pr = build_continue_loop_bootstrap_plan("create git commit")
    assert pr.terminal_after_execute is True
    assert pr.decision is not None
    assert "create git commit" in pr.decision.steps[0].full_description
