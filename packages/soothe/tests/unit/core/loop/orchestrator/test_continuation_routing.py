"""Tests for continuation routing helpers."""

from __future__ import annotations

from soothe.foundation.sloop.engine.continuation_context import build_continue_bootstrap_step_briefs
from soothe.foundation.sloop.orchestrator.continuation_routing import (
    bootstrap_terminal_after_execute,
)
from soothe.foundation.sloop.orchestrator.nodes.plan_assess import (
    build_continue_loop_bootstrap_plan,
)


def test_bootstrap_uses_goal_description() -> None:
    briefs = build_continue_bootstrap_step_briefs(
        user_goal="create git commit",
        goal_description="Create git commit for the completed fixes",
    )
    assert briefs.full_description == "Create git commit for the completed fixes"


def test_bootstrap_terminal_after_execute_for_refined_intent() -> None:
    assert (
        bootstrap_terminal_after_execute(
            raw_user_goal="create git commit",
            goal_description="Create git commit for the completed fixes",
        )
        is False
    )


def test_bootstrap_terminal_after_execute_respects_multi_phase() -> None:
    assert (
        bootstrap_terminal_after_execute(
            raw_user_goal="create git commit",
            goal_description="create git commit",
            multi_phase=True,
        )
        is False
    )


def test_build_bootstrap_plan_terminal_auto_from_intent() -> None:
    pr = build_continue_loop_bootstrap_plan(
        "create git commit",
        goal_description="Create git commit for the completed fixes",
    )
    assert pr.terminal_after_execute is False
    assert pr.decision is not None
    assert pr.decision.steps[0].full_description == "Create git commit for the completed fixes"
