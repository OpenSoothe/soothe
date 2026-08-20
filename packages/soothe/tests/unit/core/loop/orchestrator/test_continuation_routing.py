"""Tests for continuation routing helpers."""

from __future__ import annotations

from types import SimpleNamespace

from soothe.sloop.engine.completion.continuation_context import build_continue_bootstrap_step_briefs
from soothe.sloop.orchestrator.continuation import (
    has_prior_goal_context,
    is_fresh_goal,
    is_structural_continuation,
)


def test_bootstrap_uses_user_goal() -> None:
    briefs = build_continue_bootstrap_step_briefs(user_goal="create git commit")
    assert "create git commit" in briefs.full_description
    assert briefs.description == "create git commit"


def test_is_fresh_goal_false_on_continue_loop_mode() -> None:
    ctx = SimpleNamespace(
        recovery_valid_resume=False,
        continue_loop_mode=True,
        ce=None,
        checkpoint=None,
    )
    assert is_fresh_goal(ctx) is False
    assert is_structural_continuation(ctx) is False  # no prior context


def test_has_prior_goal_context_from_checkpoint_history() -> None:
    ctx = SimpleNamespace(
        ce=None,
        ce_goal_id=None,
        checkpoint=SimpleNamespace(goal_history=[object(), object()]),
    )
    assert has_prior_goal_context(ctx) is True
