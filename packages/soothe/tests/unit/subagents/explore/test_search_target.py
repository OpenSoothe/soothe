"""Tests for explore search_target resolution (IG-326)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from soothe.subagents.explore.search_target import resolve_explore_search_target


def test_explicit_search_target_wins_over_messages() -> None:
    assert (
        resolve_explore_search_target(
            [HumanMessage(content="from message")],
            "from state",
        )
        == "from state"
    )


def test_derives_from_latest_human_message() -> None:
    msgs = [
        HumanMessage(content="first ask"),
        AIMessage(content="ok"),
        HumanMessage(content="count all file types"),
    ]
    assert resolve_explore_search_target(msgs, None) == "count all file types"


def test_derives_from_only_human_message_task_shape() -> None:
    """Mirrors task tool: single HumanMessage with subagent brief."""
    brief = "Map Python test layout under packages/soothe/tests"
    assert resolve_explore_search_target([HumanMessage(content=brief)], "") == brief


def test_multimodal_text_block_content() -> None:
    content = [{"type": "text", "text": "  find README  "}]
    assert resolve_explore_search_target([HumanMessage(content=content)], None) == "find README"


def test_empty_explicit_falls_back_to_messages() -> None:
    assert resolve_explore_search_target([HumanMessage(content="goal")], "   ") == "goal"


def test_no_messages_returns_empty() -> None:
    assert resolve_explore_search_target([], None) == ""
    assert resolve_explore_search_target(None, None) == ""
