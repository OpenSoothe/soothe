"""Tests for explore plan_search recent message window (IG-389)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from soothe.subagents.explore.engine import (
    _PLAN_SEARCH_RECENT_MESSAGES_MAX,
    recent_messages_for_explore_plan,
)


def test_recent_empty_when_no_messages() -> None:
    assert recent_messages_for_explore_plan(None) == []
    assert recent_messages_for_explore_plan([]) == []


def test_recent_non_positive_cap_returns_empty() -> None:
    msgs = [HumanMessage(content="x")]
    assert recent_messages_for_explore_plan(msgs, max_messages=0) == []
    assert recent_messages_for_explore_plan(msgs, max_messages=-1) == []


def test_recent_returns_full_list_when_under_cap() -> None:
    msgs = [
        HumanMessage(content="a"),
        AIMessage(content="b"),
        ToolMessage(content="c", tool_call_id="1"),
    ]
    assert recent_messages_for_explore_plan(msgs) == msgs


def test_recent_truncates_to_tail() -> None:
    filler = [HumanMessage(content=str(i)) for i in range(_PLAN_SEARCH_RECENT_MESSAGES_MAX + 5)]
    got = recent_messages_for_explore_plan(filler)
    assert len(got) == _PLAN_SEARCH_RECENT_MESSAGES_MAX
    assert got[0].content == "5"
    assert got[-1].content == str(_PLAN_SEARCH_RECENT_MESSAGES_MAX + 4)
