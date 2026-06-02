"""Unit tests for AutoClarificationPolicy."""

from __future__ import annotations

import pytest

from soothe.core.loop.clarification.auto import AutoClarificationPolicy
from soothe.core.loop.clarification.protocol import (
    ClarificationDeferredError,
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
async def test_low_confidence_defers() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(answers=["guess"], confidence=0.2, defer=False)
        )
    )
    with pytest.raises(ClarificationDeferredError) as exc_info:
        await policy.answer(_request())
    assert "low confidence" in exc_info.value.reason


@pytest.mark.asyncio
async def test_explicit_defer_propagates() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(answers=[], confidence=0.95, defer=True)
        )
    )
    with pytest.raises(ClarificationDeferredError) as exc_info:
        await policy.answer(_request())
    assert "explicit defer" in exc_info.value.reason


@pytest.mark.asyncio
async def test_custom_min_confidence() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(answers=["x"], confidence=0.5, defer=False)
        ),
        min_confidence=0.8,
    )
    with pytest.raises(ClarificationDeferredError):
        await policy.answer(_request())
