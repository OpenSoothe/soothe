"""Tests for LangGraph interrupt auto-resume helpers."""

from __future__ import annotations

from soothe.core.loop.engine.graph_interrupt import build_auto_resume_payload


def test_auto_resume_tool_interrupt_payload() -> None:
    pending = {
        "i1": {
            "action_requests": [{"name": "write_file", "args": {"path": "a.txt"}}],
        }
    }
    out = build_auto_resume_payload(pending)
    assert out == {"i1": {"decisions": [{"type": "approve"}]}}


def test_auto_resume_ask_user_payload() -> None:
    pending = {"i2": {"type": "ask_user", "questions": ["q1", "q2"]}}
    out = build_auto_resume_payload(pending)
    assert out == {"i2": {"answers": ["", ""]}}
