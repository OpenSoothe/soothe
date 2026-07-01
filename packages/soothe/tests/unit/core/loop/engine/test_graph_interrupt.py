"""Tests for LangGraph interrupt auto-resume helpers (RFC-622)."""

from __future__ import annotations

from soothe.foundation.sloop.engine.graph_interrupt import (
    build_auto_resume_payload,
    is_ask_user_interrupt,
)


def test_auto_resume_tool_interrupt_payload() -> None:
    pending = {
        "i1": {
            "action_requests": [{"name": "write_file", "args": {"path": "a.txt"}}],
        }
    }
    out = build_auto_resume_payload(pending)
    assert out == {"i1": {"decisions": [{"type": "approve"}]}}


def test_auto_resume_skips_ask_user_payload() -> None:
    """RFC-622: ``ask_user`` no longer auto-resumed; routed via ClarificationPolicy."""
    pending = {"i2": {"type": "ask_user", "questions": ["q1", "q2"]}}
    out = build_auto_resume_payload(pending)
    assert out == {}


def test_auto_resume_mixed_payload_keeps_action_approvals() -> None:
    pending = {
        "i1": {"action_requests": [{"name": "x"}]},
        "i2": {"type": "ask_user", "questions": ["q"]},
    }
    out = build_auto_resume_payload(pending)
    assert out == {"i1": {"decisions": [{"type": "approve"}]}}


def test_is_ask_user_interrupt_matches() -> None:
    assert is_ask_user_interrupt({"type": "ask_user", "questions": ["q"]})


def test_is_ask_user_interrupt_rejects_non_mapping_and_other_types() -> None:
    assert not is_ask_user_interrupt(None)
    assert not is_ask_user_interrupt("ask_user")
    assert not is_ask_user_interrupt({"type": "review"})
    assert not is_ask_user_interrupt({})
