"""Unit tests for veritas implementation (RFC-622, RFC-623)."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from soothe.foundation.sloop.clarification.protocol import (
    ClarificationRequest,
    LoopStateView,
)
from soothe.subagents.veritas import answer
from soothe.subagents.veritas import implementation as veritas_impl
from soothe.utils.llm.structured import StructuredOutputError


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


def _patch_returns(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    async def _fake(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return payload

    monkeypatch.setattr(veritas_impl, "invoke_structured_chat", _fake)


def _patch_raises(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
) -> None:
    async def _fake(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise exc

    monkeypatch.setattr(veritas_impl, "invoke_structured_chat", _fake)


@pytest.mark.asyncio
async def test_high_confidence_answer_returned_as_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_returns(
        monkeypatch,
        {
            "answers": ["focus on token refresh"],
            "confidence": 0.85,
            "defer": False,
            "rationale": "user explicitly mentioned auth",
        },
    )
    result = await answer(_request(), model=object())  # model unused after patch
    assert result.answers == ["focus on token refresh"]
    assert result.confidence == pytest.approx(0.85)
    assert result.defer is False


@pytest.mark.asyncio
async def test_explicit_defer_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_returns(
        monkeypatch,
        {
            "answers": [],
            "confidence": 0.0,
            "defer": True,
            "rationale": "I genuinely do not know",
        },
    )
    result = await answer(_request(num_q=2), model=object())
    assert result.defer is True
    assert result.rationale == "I genuinely do not know"


@pytest.mark.asyncio
async def test_answer_ending_with_question_coerced_to_defer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_returns(
        monkeypatch,
        {
            "answers": ["should we use JWT?"],
            "confidence": 0.9,
            "defer": False,
            "rationale": "unclear",
        },
    )
    result = await answer(_request(), model=object())
    assert result.defer is True
    assert result.confidence == pytest.approx(0.0)
    assert result.rationale == "answer_was_question"


@pytest.mark.asyncio
async def test_structured_output_failure_coerced_to_defer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_raises(monkeypatch, StructuredOutputError("validation failed: minItems"))
    result = await answer(_request(num_q=2), model=object())
    assert result.defer is True
    assert result.confidence == pytest.approx(0.0)
    assert result.rationale.startswith("structured_output_failed:")
    assert result.answers == []


def test_fakelist_model_import_for_sanity() -> None:
    # Lightweight sanity: ensure langchain test util is available without using it.
    assert FakeListChatModel is not None


@pytest.mark.asyncio
async def test_traced_invoke_config_forwarded_when_config_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """soothe_config + thread/loop ids → invoke_structured_chat receives a config."""
    captured: dict[str, Any] = {}

    async def _fake(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["config"] = kwargs.get("config")
        return {"answers": ["go"], "confidence": 0.8, "defer": False, "rationale": "ok"}

    monkeypatch.setattr(veritas_impl, "invoke_structured_chat", _fake)

    sentinel = {"metadata": {"purpose": "clarification_answer"}, "callbacks": ["lf"]}

    class _StubTracer:
        def traced_llm(self, **_kwargs: Any) -> dict[str, Any]:
            return sentinel

    monkeypatch.setattr(
        "soothe_nano.utils.observability.langfuse.SootheLangfuse",
        lambda _cfg: _StubTracer(),
        raising=True,
    )

    class _StubCfg:
        class observability:  # noqa: N801
            class langfuse:  # noqa: N801
                trace_name = "soothe-dev"

    await answer(
        _request(),
        model=object(),
        soothe_config=_StubCfg(),  # type: ignore[arg-type]
        thread_id="tid",
        loop_id="lid",
    )
    assert captured["config"] is sentinel


@pytest.mark.asyncio
async def test_traced_invoke_config_none_when_config_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No soothe_config → invoke_structured_chat receives config=None."""
    captured: dict[str, Any] = {}

    async def _fake(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["config"] = kwargs.get("config")
        return {"answers": ["go"], "confidence": 0.8, "defer": False, "rationale": "ok"}

    monkeypatch.setattr(veritas_impl, "invoke_structured_chat", _fake)

    await answer(_request(), model=object())
    assert captured["config"] is None
