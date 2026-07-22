"""Tests for continuation_context helpers."""

from __future__ import annotations

from soothe.sloop.engine.continuation_context import (
    build_continuation_execution_hints,
    build_continue_bootstrap_step_briefs,
    ledger_goal_completion_text,
)
from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_ledger_goal_completion_text_returns_latest_ai_body() -> None:
    ledger = [
        LoopHumanMessage(content="old", phase="goal_completion"),
        LoopAIMessage(content="older report", phase="goal_completion"),
        LoopHumanMessage(content="new", phase="goal_completion"),
        LoopAIMessage(content="final synthesis report", phase="goal_completion"),
    ]
    assert ledger_goal_completion_text(ledger) == "final synthesis report"


def test_ledger_goal_completion_text_ignores_execute_step() -> None:
    ledger = [
        LoopHumanMessage(content="step", phase="execute_step"),
        LoopAIMessage(content="execute answer only", phase="execute_step"),
    ]
    assert ledger_goal_completion_text(ledger) == ""


def test_build_continuation_execution_hints_when_prior_present() -> None:
    body = build_continuation_execution_hints(has_prior_goal_completion=True)
    assert "projected prior goal completion report" in body.instructions


def test_build_continue_bootstrap_step_briefs_continue_keyword() -> None:
    briefs = build_continue_bootstrap_step_briefs(user_goal="continue")
    assert "completion report" in briefs.full_description.lower()


def test_build_continue_bootstrap_step_briefs_custom_goal() -> None:
    briefs = build_continue_bootstrap_step_briefs(user_goal="implement the recommended fixes")
    assert "projected completion report" in briefs.full_description.lower()
