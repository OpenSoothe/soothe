"""Tests for status vocabulary bridge helpers."""

from __future__ import annotations

from soothe.sloop.state.status_vocabulary import (
    is_goal_index_in_flight,
    suggest_loop_checkpoint_status,
)


def test_goal_index_in_flight_only_running() -> None:
    assert is_goal_index_in_flight("running") is True
    assert is_goal_index_in_flight("completed") is False


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
