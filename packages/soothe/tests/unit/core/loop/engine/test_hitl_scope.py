"""Tests for AgentLoop HITL scope helpers."""

from __future__ import annotations

from soothe.core.loop.engine.hitl_scope import (
    auto_approve_interrupt_resume_payload,
    timeout_default_hitl_resume_payload,
)


def test_auto_approve_tool_hitl_payload() -> None:
    pending = {
        "i1": {
            "action_requests": [{"name": "write_file", "args": {"path": "a.txt"}}],
        }
    }
    out = auto_approve_interrupt_resume_payload(pending)
    assert out == {"i1": {"decisions": [{"type": "approve"}]}}


def test_auto_approve_ask_user_payload() -> None:
    pending = {"i2": {"type": "ask_user", "questions": ["q1", "q2"]}}
    out = auto_approve_interrupt_resume_payload(pending)
    assert out == {"i2": {"answers": ["", ""]}}


def test_timeout_default_ask_user_first_choice() -> None:
    pending = {
        "u1": {
            "type": "ask_user",
            "questions": [
                {
                    "question": "Pick",
                    "choices": [
                        {"label": "A", "value": "alpha"},
                        {"label": "B", "value": "beta"},
                    ],
                    "other": False,
                }
            ],
        }
    }
    out = timeout_default_hitl_resume_payload(pending)
    assert out == {"u1": {"answers": ["alpha"]}}


def test_timeout_default_mixed_tool_and_ask_user() -> None:
    pending = {
        "t1": {"action_requests": [{"name": "read_file", "args": {}}]},
        "u1": {
            "type": "ask_user",
            "questions": [{"question": "x", "choices": None, "other": False}],
        },
    }
    out = timeout_default_hitl_resume_payload(pending)
    assert out["t1"] == {"decisions": [{"type": "approve"}]}
    assert out["u1"] == {"answers": [""]}
