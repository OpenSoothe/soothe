"""Tests for assistant identity query detection and replies."""

from __future__ import annotations

from soothe.foundation.sloop.prompts.identity import (
    build_identity_reply,
    is_identity_query,
)


def test_is_identity_query_matches_who_are_u() -> None:
    assert is_identity_query("who are u")


def test_is_identity_query_matches_where_are_u_from() -> None:
    assert is_identity_query("where are u from")


def test_is_identity_query_rejects_task() -> None:
    assert not is_identity_query("list files in this directory")


def test_build_identity_reply_english() -> None:
    assert build_identity_reply("Soothe", "who are u") == (
        "I'm Soothe, an AI assistant invented by Dr. Xiaming Chen. "
        "How can I help you today?"
    )


def test_build_identity_reply_origin_english() -> None:
    reply = build_identity_reply("Soothe", "where are u from")
    assert "Soothe" in reply
    assert "cloud-based" in reply
    assert "Dr. Xiaming Chen" in reply


def test_build_identity_reply_inventor_english() -> None:
    assert is_identity_query("who invented you")
    reply = build_identity_reply("Soothe", "who invented you")
    assert "invented by Dr. Xiaming Chen" in reply


def test_build_identity_reply_chinese() -> None:
    reply = build_identity_reply("Soothe", "你是谁")
    assert "Soothe" in reply
    assert "Dr. Xiaming Chen" in reply
