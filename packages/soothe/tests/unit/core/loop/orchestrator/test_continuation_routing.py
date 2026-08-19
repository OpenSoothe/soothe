"""Tests for continuation routing helpers."""

from __future__ import annotations

from soothe.sloop.engine.continuation_context import build_continue_bootstrap_step_briefs
from soothe.sloop.orchestrator.continuation import (
    bootstrap_terminal_after_execute,
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
