"""Resume topic resolution for loop_list RPC."""

from __future__ import annotations

from soothe_daemon.protocol.router import _resolve_loop_topic


def test_resolve_loop_topic_uses_stored_topic_when_present() -> None:
    assert (
        _resolve_loop_topic(
            prompt="Build the auth module",
            resume_topic="Auth module build",
        )
        == "Auth module build"
    )


def test_resolve_loop_topic_falls_back_to_goal_text() -> None:
    assert (
        _resolve_loop_topic(
            prompt="Long original goal text",
            resume_topic=None,
        )
        == "Long original goal text"
    )


def test_resolve_loop_topic_no_goal_placeholder() -> None:
    assert _resolve_loop_topic(prompt=None, resume_topic=None) == "(no goal)"
