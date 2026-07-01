"""Resume topic resolution for loop_list RPC."""

from __future__ import annotations

from soothe_daemon.protocol.router import _resolve_loop_topic


def test_resolve_loop_topic_uses_goal_before_completion() -> None:
    assert (
        _resolve_loop_topic(
            goals_completed=0,
            prompt="Build the auth module",
            resume_topic=None,
        )
        == "Build the auth module"
    )


def test_resolve_loop_topic_uses_stored_summary_after_completion() -> None:
    assert (
        _resolve_loop_topic(
            goals_completed=1,
            prompt="Long original goal text",
            resume_topic="Auth module build",
        )
        == "Auth module build"
    )


def test_resolve_loop_topic_falls_back_to_goal_while_summary_pending() -> None:
    assert (
        _resolve_loop_topic(
            goals_completed=1,
            prompt="Long original goal text",
            resume_topic=None,
        )
        == "Long original goal text"
    )
