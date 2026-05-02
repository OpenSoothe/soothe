"""Tests for Plan-phase prompt metrics helpers (IG-353)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from soothe.cognition.agent_loop.core.planner import _plan_prompt_text_length


def test_plan_prompt_text_length_plain_strings() -> None:
    msgs = [
        SystemMessage(content="abc"),
        HumanMessage(content="defgh"),
    ]
    assert _plan_prompt_text_length(msgs) == 8


def test_plan_prompt_text_length_text_blocks() -> None:
    msgs = [
        HumanMessage(content=[{"type": "text", "text": "hello"}]),
    ]
    assert _plan_prompt_text_length(msgs) == 5


def test_plan_prompt_text_length_mixed_list() -> None:
    msgs = [
        HumanMessage(content=["x", {"type": "text", "text": "yy"}]),
    ]
    assert _plan_prompt_text_length(msgs) == 3
