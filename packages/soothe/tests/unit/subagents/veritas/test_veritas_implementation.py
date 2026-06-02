"""Unit tests for veritas implementation."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from soothe.core.loop.clarification.protocol import (
    ClarificationRequest,
    LoopStateView,
)
from soothe.subagents.veritas import answer
from soothe.subagents.veritas.schemas import VeritasAnswerSchema


def _request(num_q: int = 1) -> ClarificationRequest:
    return ClarificationRequest(
        questions=tuple(f"q{i}" for i in range(num_q)),
        origin_node="execute",
        origin_interrupt_id="i",
        loop_state=LoopStateView(
            goal_id="g",
            goal_description="refine the auth module",
            user_request="please refine auth",
            iteration=2,
            intent_classification="agentic",
            plan_summary="explored auth/",
            recent_step_outputs=("read auth/main.py",),
            workspace_summary="src/auth/",
            active_skills=("platonic-coding",),
            active_mcp_servers=(),
        ),
    )


class _StubStructuredModel:
    """Mimics ``BaseChatModel.with_structured_output(VeritasAnswerSchema)``."""

    def __init__(self, schema_instance: VeritasAnswerSchema) -> None:
        self._instance = schema_instance

    async def ainvoke(self, _messages: Any, **_kwargs: Any) -> VeritasAnswerSchema:
        return self._instance


class _StubChatModel:
    def __init__(self, schema_instance: VeritasAnswerSchema) -> None:
        self._instance = schema_instance

    def with_structured_output(self, _schema: type[VeritasAnswerSchema]) -> Any:
        return _StubStructuredModel(self._instance)


@pytest.mark.asyncio
async def test_high_confidence_answer_returned_as_is() -> None:
    schema = VeritasAnswerSchema(
        answers=["focus on token refresh"],
        confidence=0.85,
        defer=False,
        rationale="user explicitly mentioned auth",
    )
    model = _StubChatModel(schema)
    result = await answer(_request(), model=model)
    assert result.answers == ["focus on token refresh"]
    assert result.confidence == pytest.approx(0.85)
    assert result.defer is False


@pytest.mark.asyncio
async def test_answer_ending_with_question_coerced_to_defer() -> None:
    schema = VeritasAnswerSchema(
        answers=["should we use JWT?"],
        confidence=0.9,
        defer=False,
        rationale="unclear",
    )
    model = _StubChatModel(schema)
    result = await answer(_request(), model=model)
    assert result.defer is True
    assert result.confidence == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_answer_count_mismatch_coerced_to_defer() -> None:
    schema = VeritasAnswerSchema(
        answers=["only one"],
        confidence=0.9,
        defer=False,
    )
    model = _StubChatModel(schema)
    result = await answer(_request(num_q=2), model=model)
    assert result.defer is True


@pytest.mark.asyncio
async def test_rejects_unexpected_structured_output_type() -> None:
    class _Bad:
        def with_structured_output(self, _schema: type[VeritasAnswerSchema]) -> Any:
            class _Inner:
                async def ainvoke(self, _msgs: Any, **_kw: Any) -> Any:
                    return {"not": "a model"}

            return _Inner()

    with pytest.raises(TypeError):
        await answer(_request(), model=_Bad())


def test_fakelist_model_import_for_sanity() -> None:
    # Lightweight sanity: ensure langchain test util is available without using it.
    assert FakeListChatModel is not None
