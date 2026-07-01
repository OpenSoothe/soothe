"""Unit tests for ClarificationDetector (structured ``ask_user`` only)."""

from __future__ import annotations

from soothe.foundation.sloop.clarification.detector import ClarificationDetector
from soothe.foundation.sloop.clarification.protocol import LoopStateView


def _view() -> LoopStateView:
    return LoopStateView(
        goal_id="g",
        goal_description="",
        user_request="",
        iteration=0,
        intent_classification=None,
        plan_summary=None,
        recent_step_outputs=(),
        workspace_summary=None,
        active_skills=(),
        active_mcp_servers=(),
    )


def test_from_interrupt_matches_ask_user_with_questions_list() -> None:
    det = ClarificationDetector()
    req = det.from_interrupt(
        {"type": "ask_user", "questions": ["What to refine?"]},
        interrupt_id="i1",
        origin_node="execute",
        loop_state=_view(),
    )
    assert req is not None
    assert req.questions == ("What to refine?",)
    assert req.origin_interrupt_id == "i1"
    assert req.origin_node == "execute"


def test_from_interrupt_matches_ask_user_with_singular_question() -> None:
    det = ClarificationDetector()
    req = det.from_interrupt(
        {"type": "ask_user", "question": "Are you sure?"},
        interrupt_id="i2",
        origin_node="plan_generate",
        loop_state=_view(),
    )
    assert req is not None
    assert req.questions == ("Are you sure?",)


def test_from_interrupt_returns_none_for_non_ask_user() -> None:
    det = ClarificationDetector()
    assert (
        det.from_interrupt(
            {"action_requests": [{"name": "write"}]},
            interrupt_id="i3",
            origin_node="execute",
            loop_state=_view(),
        )
        is None
    )


def test_from_interrupt_returns_none_for_empty_questions() -> None:
    det = ClarificationDetector()
    assert (
        det.from_interrupt(
            {"type": "ask_user", "questions": []},
            interrupt_id="i4",
            origin_node="execute",
            loop_state=_view(),
        )
        is None
    )


def test_from_interrupt_strips_whitespace_and_filters_blanks() -> None:
    det = ClarificationDetector()
    req = det.from_interrupt(
        {"type": "ask_user", "questions": ["  ", " real question ", ""]},
        interrupt_id="i5",
        origin_node="plan_assess",
        loop_state=_view(),
    )
    assert req is not None
    assert req.questions == ("real question",)


def test_from_interrupt_rejects_non_mapping() -> None:
    det = ClarificationDetector()
    assert (
        det.from_interrupt(
            "ask_user",
            interrupt_id="i6",
            origin_node="execute",
            loop_state=_view(),
        )
        is None
    )
