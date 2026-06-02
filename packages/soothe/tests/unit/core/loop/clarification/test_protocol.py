"""Unit tests for clarification protocol dataclasses and (de)serialization."""

from __future__ import annotations

import pytest

from soothe.core.loop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationDeferredError,
    ClarificationRequest,
    LoopStateView,
    answer_from_state,
    answer_to_state,
    request_from_state,
    request_to_state,
)


def _view() -> LoopStateView:
    return LoopStateView(
        goal_id="g1",
        goal_description="refine auth module",
        user_request="please refine the auth module",
        iteration=3,
        intent_classification="agentic",
        plan_summary="step 1 done",
        recent_step_outputs=("out1", "out2"),
        workspace_summary="src/",
        active_skills=("platonic-coding",),
        active_mcp_servers=(),
    )


def _request() -> ClarificationRequest:
    return ClarificationRequest(
        questions=("What aspect to refine?",),
        origin_node="execute",
        origin_interrupt_id="i1",
        loop_state=_view(),
    )


def test_request_roundtrip() -> None:
    original = _request()
    serialized = request_to_state(original)
    assert isinstance(serialized, dict)
    restored = request_from_state(serialized)
    assert restored == original


def test_request_from_state_rejects_unknown_origin() -> None:
    bad = request_to_state(_request())
    bad["origin_node"] = "garbage"
    with pytest.raises(ValueError):
        request_from_state(bad)


def test_answer_roundtrip() -> None:
    original = ClarificationAnswer(
        answers=("auth flows",),
        source="veritas",
        confidence=0.8,
        defer=False,
        audit={"rationale": "user asked to refine auth"},
    )
    restored = answer_from_state(answer_to_state(original))
    assert restored == original


def test_answer_from_state_rejects_unknown_source() -> None:
    bad = answer_to_state(ClarificationAnswer(answers=(), source="human", confidence=None))
    bad["source"] = "robot"
    with pytest.raises(ValueError):
        answer_from_state(bad)


def test_clarification_deferred_carries_request() -> None:
    req = _request()
    exc = ClarificationDeferredError("low confidence", req)
    assert exc.reason == "low confidence"
    assert exc.request is req
    assert str(exc) == "low confidence"


def test_view_roundtrip_preserves_empty_collections() -> None:
    req = ClarificationRequest(
        questions=("q",),
        origin_node="plan_assess",
        origin_interrupt_id="i",
        loop_state=LoopStateView(
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
        ),
    )
    assert request_from_state(request_to_state(req)) == req
