"""Unit tests for shared goal-entry helpers (IG-676)."""

from __future__ import annotations

from types import SimpleNamespace

from soothe.sloop.orchestrator.continuation_routing import (
    FRESH_LOOP_BYPASS_PREFIX,
    FRESH_LOOP_BYPASS_REASON,
    fresh_loop_bypass_assessment,
    has_prior_goal_context,
    is_fresh_goal,
    is_fresh_loop_skip_evaluate,
    is_structural_continuation,
)


def test_fresh_loop_bypass_reason_uses_stable_prefix() -> None:
    assert FRESH_LOOP_BYPASS_REASON.startswith(FRESH_LOOP_BYPASS_PREFIX)
    assessment = fresh_loop_bypass_assessment()
    assert assessment.assessment_reasoning.startswith(FRESH_LOOP_BYPASS_PREFIX)


def test_has_prior_goal_context_from_completed_ce_goal() -> None:
    prior = SimpleNamespace(
        id="g0",
        status="completed",
        action_history=[],
        steps=SimpleNamespace(nodes={}),
    )
    ctx = SimpleNamespace(
        ce=SimpleNamespace(get_all_goals=lambda: [prior]),
        ce_goal_id="g1",
        checkpoint=None,
    )
    assert has_prior_goal_context(ctx) is True


def test_is_fresh_goal_false_when_continue_loop_mode() -> None:
    ctx = SimpleNamespace(
        recovery_valid_resume=False,
        continue_loop_mode=True,
        ce=SimpleNamespace(get_all_goals=lambda: []),
        ce_goal_id=None,
        checkpoint=None,
    )
    assert is_fresh_goal(ctx) is False
    assert is_structural_continuation(ctx) is False


def test_is_fresh_loop_skip_evaluate_requires_ce_and_iter0() -> None:
    ctx = SimpleNamespace(
        recovery_valid_resume=False,
        continue_loop_mode=False,
        ce=None,
        ce_goal_id=None,
        checkpoint=None,
        loop_state=SimpleNamespace(iteration=0, step_results=[]),
    )
    assert is_fresh_goal(ctx) is True
    assert is_fresh_loop_skip_evaluate(ctx) is False
