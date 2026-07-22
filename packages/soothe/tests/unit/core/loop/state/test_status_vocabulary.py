"""Tests for status vocabulary bridge helpers."""

from __future__ import annotations

from soothe.sloop.state.status_vocabulary import (
    ce_goal_status_to_goal_index,
    goal_index_status_to_ce,
    is_ce_goal_in_flight,
    is_goal_index_in_flight,
    suggest_loop_checkpoint_status,
)


def test_goal_index_in_flight_only_running() -> None:
    assert is_goal_index_in_flight("running") is True
    assert is_goal_index_in_flight("completed") is False


def test_ce_goal_in_flight_active_and_clarification() -> None:
    assert is_ce_goal_in_flight("active") is True
    assert is_ce_goal_in_flight("awaiting_clarification") is True
    assert is_ce_goal_in_flight("completed") is False


def test_ce_to_goal_index_mapping() -> None:
    assert ce_goal_status_to_goal_index("active") == "running"
    assert ce_goal_status_to_goal_index("completed") == "completed"
    assert ce_goal_status_to_goal_index("failed") == "failed"


def test_goal_index_to_ce_mapping() -> None:
    assert goal_index_status_to_ce("running") == "active"
    assert goal_index_status_to_ce("completed") == "completed"


def test_suggest_loop_status_when_idle_with_running_goals() -> None:
    assert (
        suggest_loop_checkpoint_status(
            loop_status="idle",
            goal_index_statuses=["completed", "running"],
        )
        == "running"
    )


def test_suggest_loop_status_idle_when_no_in_flight_goals() -> None:
    assert (
        suggest_loop_checkpoint_status(
            loop_status="idle",
            goal_index_statuses=["completed", "completed"],
        )
        == "idle"
    )
