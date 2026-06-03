"""Unit tests for AutoClarificationPolicy (RFC-622, RFC-623)."""

from __future__ import annotations

import pytest

from soothe.core.loop.clarification.auto import AutoClarificationPolicy
from soothe.core.loop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationDeferredError,
    ClarificationPolicy,
    ClarificationRequest,
    LoopStateView,
)
from soothe.subagents.veritas.schemas import VeritasAnswerSchema


def _request() -> ClarificationRequest:
    return ClarificationRequest(
        questions=("What aspect to refine?",),
        origin_node="execute",
        origin_interrupt_id="i1",
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


def _veritas_returning(schema: VeritasAnswerSchema):
    async def _fn(_req: ClarificationRequest) -> VeritasAnswerSchema:
        return schema

    return _fn


class _RecordingFallback:
    """Stand-in ClarificationPolicy that records invocations."""

    def __init__(self, answer: ClarificationAnswer) -> None:
        self._answer = answer
        self.calls: list[ClarificationRequest] = []

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        self.calls.append(request)
        return self._answer


@pytest.mark.asyncio
async def test_high_confidence_returns_answer() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=["auth flows"],
                confidence=0.9,
                defer=False,
                rationale="user said refine auth",
            )
        )
    )
    ans = await policy.answer(_request())
    assert ans.source == "veritas"
    assert ans.answers == ("auth flows",)
    assert ans.confidence == pytest.approx(0.9)
    assert ans.audit == {"rationale": "user said refine auth"}


@pytest.mark.asyncio
async def test_low_confidence_defers_with_kind() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(VeritasAnswerSchema(answers=["guess"], confidence=0.2, defer=False))
    )
    with pytest.raises(ClarificationDeferredError) as exc_info:
        await policy.answer(_request())
    assert "low confidence" in exc_info.value.reason
    assert exc_info.value.kind == "low_confidence"


@pytest.mark.asyncio
async def test_explicit_defer_propagates_with_kind() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[], confidence=0.95, defer=True, rationale="legitimate uncertainty"
            )
        )
    )
    with pytest.raises(ClarificationDeferredError) as exc_info:
        await policy.answer(_request())
    assert "explicit defer" in exc_info.value.reason
    assert exc_info.value.kind == "explicit"


@pytest.mark.asyncio
async def test_custom_min_confidence() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(VeritasAnswerSchema(answers=["x"], confidence=0.5, defer=False)),
        min_confidence=0.8,
    )
    with pytest.raises(ClarificationDeferredError) as exc_info:
        await policy.answer(_request())
    assert exc_info.value.kind == "low_confidence"


@pytest.mark.asyncio
async def test_answer_was_question_kind() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[],
                confidence=0.0,
                defer=True,
                rationale="answer_was_question",
            )
        )
    )
    with pytest.raises(ClarificationDeferredError) as exc_info:
        await policy.answer(_request())
    assert exc_info.value.kind == "answer_was_question"
    assert "question" in exc_info.value.reason


@pytest.mark.asyncio
async def test_structured_output_failed_no_fallback_raises() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[],
                confidence=0.0,
                defer=True,
                rationale="structured_output_failed: validation failed: minItems",
            )
        )
    )
    with pytest.raises(ClarificationDeferredError) as exc_info:
        await policy.answer(_request())
    assert exc_info.value.kind == "structured_output_failed"
    assert "structured output failed" in exc_info.value.reason


@pytest.mark.asyncio
async def test_structured_output_failed_delegates_to_fallback() -> None:
    fallback_answer = ClarificationAnswer(
        answers=("operator says auth",), source="human", confidence=None
    )
    fallback = _RecordingFallback(fallback_answer)
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[],
                confidence=0.0,
                defer=True,
                rationale="structured_output_failed: provider error",
            )
        ),
        interactive_fallback=fallback,
    )
    request = _request()
    ans = await policy.answer(request)
    assert ans is fallback_answer
    assert fallback.calls == [request]


@pytest.mark.asyncio
async def test_explicit_defer_does_not_use_fallback() -> None:
    """Only structured_output_failed should reach the fallback (RFC-623)."""
    fallback_answer = ClarificationAnswer(answers=("x",), source="human", confidence=None)
    fallback: ClarificationPolicy = _RecordingFallback(fallback_answer)
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[], confidence=0.0, defer=True, rationale="real uncertainty"
            )
        ),
        interactive_fallback=fallback,
    )
    with pytest.raises(ClarificationDeferredError) as exc_info:
        await policy.answer(_request())
    assert exc_info.value.kind == "explicit"
    assert isinstance(fallback, _RecordingFallback)
    assert fallback.calls == []
