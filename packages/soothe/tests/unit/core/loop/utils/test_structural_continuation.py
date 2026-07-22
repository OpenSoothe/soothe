"""Tests for structural loop-continuation controls (IG-558)."""

from __future__ import annotations

from datetime import UTC, datetime

from soothe.sloop.state.execution_checkpoint import GoalIndexEntry
from soothe.sloop.utils.structural_continuation import (
    chitchat_may_finalize_checkpoint,
    has_active_running_goal,
    is_loop_continuation_phrase,
    is_loop_control_signal,
    should_bypass_pass1_social_fast_path,
)


def _goal(*, status: str = "running") -> GoalIndexEntry:
    now = datetime.now(UTC)
    return GoalIndexEntry(
        goal_id="goal-0",
        status=status,  # type: ignore[arg-type]
        thread_id="loop-1",
        started_at=now,
        completed_at=None,
        duration_ms=0,
        tokens_used=0,
    )


def _checkpoint(*, status: str, goal_status: str = "running", current_goal_index: int = 0):
    from types import SimpleNamespace

    return SimpleNamespace(
        status=status,
        current_goal_index=current_goal_index,
        goal_history=[_goal(status=goal_status)],
    )


def test_loop_continuation_phrase_matches_common_resume_text() -> None:
    assert is_loop_continuation_phrase("continue this loop")
    assert is_loop_continuation_phrase("Continue current loop")
    assert is_loop_continuation_phrase("continue this loop to finish all")
    assert is_loop_continuation_phrase("resume the loop")


def test_loop_continuation_phrase_matches_embedded_resume_text() -> None:
    assert is_loop_continuation_phrase("Finish the integration tests, then continue the loop")
    assert is_loop_continuation_phrase("Run the suite again. continue this loop")


def test_loop_continuation_phrase_rejects_unrelated_text() -> None:
    assert not is_loop_continuation_phrase("continue cleaning")
    assert not is_loop_continuation_phrase("thanks")
    assert not is_loop_continuation_phrase("")


def test_is_loop_control_signal_includes_keyword_and_phrase() -> None:
    assert is_loop_control_signal("continue")
    assert is_loop_control_signal("continue this loop")
    assert not is_loop_control_signal("hello")


def test_should_bypass_pass1_for_control_phrase_on_idle_checkpoint() -> None:
    checkpoint = _checkpoint(status="idle", goal_status="completed", current_goal_index=-1)
    assert should_bypass_pass1_social_fast_path(checkpoint, "continue this loop")


def test_should_not_bypass_pass1_for_social_on_running_checkpoint() -> None:
    checkpoint = _checkpoint(status="running", goal_status="running")
    assert not should_bypass_pass1_social_fast_path(checkpoint, "thanks")


def test_should_not_bypass_pass1_for_social_on_idle_without_running_goal() -> None:
    checkpoint = _checkpoint(status="idle", goal_status="completed", current_goal_index=-1)
    assert not should_bypass_pass1_social_fast_path(checkpoint, "thanks")


def test_has_active_running_goal() -> None:
    assert has_active_running_goal(_checkpoint(status="running", goal_status="running"))
    assert not has_active_running_goal(_checkpoint(status="idle", goal_status="completed"))


def test_chitchat_finalize_allowed_only_on_idle_checkpoint() -> None:
    assert chitchat_may_finalize_checkpoint(_checkpoint(status="idle", goal_status="completed"))
    assert not chitchat_may_finalize_checkpoint(
        _checkpoint(status="running", goal_status="running")
    )
    assert not chitchat_may_finalize_checkpoint(None)
