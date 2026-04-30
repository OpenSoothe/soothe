"""Tests for pending AIMessage / tool-call resolution (IG-326)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage

from soothe.subagents.explore.engine import pending_tool_ai_index_and_message


def test_finds_latest_ai_when_tail_is_tool_message() -> None:
    ai = AIMessage(
        content="",
        tool_calls=[ToolCall(name="ls", args={"path": "."}, id="call-1")],
    )
    msgs = [
        HumanMessage(content="go"),
        ai,
        ToolMessage(content="ok", tool_call_id="call-1", name="ls"),
    ]
    assert pending_tool_ai_index_and_message(msgs) is None


def test_finds_pending_after_prior_round_answered() -> None:
    ai1 = AIMessage(
        content="",
        tool_calls=[ToolCall(name="ls", args={"path": "."}, id="c1")],
    )
    ai2 = AIMessage(
        content="",
        tool_calls=[ToolCall(name="glob", args={"pattern": "**/*.py"}, id="c2")],
    )
    msgs = [
        HumanMessage(content="go"),
        ai1,
        ToolMessage(content="a", tool_call_id="c1", name="ls"),
        ai2,
    ]
    got = pending_tool_ai_index_and_message(msgs)
    assert got is not None
    idx, m = got
    assert idx == len(msgs) - 1
    assert m is ai2


def test_partial_tool_replies_still_pending() -> None:
    ai = AIMessage(
        content="",
        tool_calls=[
            ToolCall(name="ls", args={"path": "."}, id="a"),
            ToolCall(name="glob", args={"pattern": "*"}, id="b"),
        ],
    )
    msgs = [
        HumanMessage(content="go"),
        ai,
        ToolMessage(content="x", tool_call_id="a", name="ls"),
    ]
    got = pending_tool_ai_index_and_message(msgs)
    assert got is not None
    assert got[1] is ai
