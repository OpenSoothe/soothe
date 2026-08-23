"""Unit tests for veritas implementation (RFC-622, RFC-623)."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from soothe_nano.llm.structured import StructuredOutputError

from soothe.sloop.clarification.protocol import (
    ClarificationRequest,
    LoopStateView,
)
from soothe.subagents.veritas import answer
from soothe.subagents.veritas import implementation as veritas_impl


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

    monkeypatch.setattr(veritas_impl, "ainvoke_structured_traced", _fake)


def _patch_raises(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
) -> None:
    async def _fake(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise exc

    monkeypatch.setattr(veritas_impl, "ainvoke_structured_traced", _fake)


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
    """Soothe config and correlation ids reach nano's traced interface."""
    captured: dict[str, Any] = {}

    async def _fake(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"answers": ["go"], "confidence": 0.8, "defer": False, "rationale": "ok"}

    monkeypatch.setattr(veritas_impl, "ainvoke_structured_traced", _fake)

    class _StubCfg:
        class observability:  # noqa: N801
            class langfuse:  # noqa: N801
                trace_name = "soothe-dev"

    cfg = _StubCfg()
    await answer(
        _request(),
        model=object(),
        soothe_config=cfg,  # type: ignore[arg-type]
        thread_id="tid",
        loop_id="lid",
    )
    assert captured["soothe_config"] is cfg
    assert captured["session_id"] == "tid"
    assert captured["loop_id"] == "lid"
    assert captured["purpose"] == "clarification_answer"


@pytest.mark.asyncio
async def test_traced_invoke_config_none_when_config_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No process config remains supported for isolated callers."""
    captured: dict[str, Any] = {}

    async def _fake(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"answers": ["go"], "confidence": 0.8, "defer": False, "rationale": "ok"}

    monkeypatch.setattr(veritas_impl, "ainvoke_structured_traced", _fake)

    await answer(_request(), model=object())
    assert captured["soothe_config"] is None


@pytest.mark.asyncio
async def test_transient_failure_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient exceptions (non-StructuredOutputError) are retried."""
    call_count = 0

    async def _fake_sleep(_seconds: float) -> None:
        pass

    async def _fake(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("transient")
        return {
            "answers": ["ok"],
            "confidence": 0.8,
            "defer": False,
            "rationale": "recovered",
            "answer_is_question": [False],
        }

    monkeypatch.setattr(veritas_impl, "ainvoke_structured_traced", _fake)
    monkeypatch.setattr(veritas_impl.asyncio, "sleep", _fake_sleep)
    result = await answer(_request(), model=object(), max_retries=3, retry_backoff_seconds=0.0)
    assert call_count == 3
    assert result.defer is False
    assert result.answers == ["ok"]


@pytest.mark.asyncio
async def test_transient_failure_exhausts_retries_to_defer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When retries are exhausted, defer with transient_failure rationale."""

    async def _fake_sleep(_seconds: float) -> None:
        pass

    async def _fake(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise TimeoutError("timed out")

    monkeypatch.setattr(veritas_impl, "ainvoke_structured_traced", _fake)
    monkeypatch.setattr(veritas_impl.asyncio, "sleep", _fake_sleep)
    result = await answer(_request(), model=object(), max_retries=1, retry_backoff_seconds=0.0)
    assert result.defer is True
    assert result.rationale.startswith("transient_failure:")


@pytest.mark.asyncio
async def test_structured_output_error_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """StructuredOutputError defers immediately — no retry."""

    async def _fake_sleep(_seconds: float) -> None:
        pass

    call_count = 0

    async def _fake(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        raise StructuredOutputError("malformed")

    monkeypatch.setattr(veritas_impl, "ainvoke_structured_traced", _fake)
    monkeypatch.setattr(veritas_impl.asyncio, "sleep", _fake_sleep)
    result = await answer(_request(), model=object(), max_retries=3, retry_backoff_seconds=0.0)
    assert result.defer is True
    assert result.rationale.startswith("structured_output_failed:")
    assert call_count == 1  # no retry


@pytest.mark.asyncio
async def test_answer_is_question_structured_field_coerces_to_defer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When model self-classifies an answer as a question via answer_is_question."""
    _patch_returns(
        monkeypatch,
        {
            "answers": ["should we use JWT?"],
            "confidence": 0.9,
            "defer": False,
            "rationale": "unclear",
            "answer_is_question": [True],
        },
    )
    result = await answer(_request(), model=object())
    assert result.defer is True
    assert result.rationale == "answer_was_question"


@pytest.mark.asyncio
async def test_answer_is_question_false_not_coerced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When model self-classifies answers as non-questions, no defer."""
    _patch_returns(
        monkeypatch,
        {
            "answers": ["use JWT"],
            "confidence": 0.9,
            "defer": False,
            "rationale": "user said JWT",
            "answer_is_question": [False],
        },
    )
    result = await answer(_request(), model=object())
    assert result.defer is False
    assert result.answers == ["use JWT"]


@pytest.mark.asyncio
async def test_reasoning_logged_in_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reasoning field is preserved in the result."""
    _patch_returns(
        monkeypatch,
        {
            "answers": ["focus on token refresh"],
            "confidence": 0.85,
            "defer": False,
            "rationale": "user mentioned auth",
            "reasoning": "The user asked about auth, token refresh is the key.",
            "answer_is_question": [False],
        },
    )
    result = await answer(_request(), model=object())
    assert result.reasoning == "The user asked about auth, token refresh is the key."


@pytest.mark.asyncio
async def test_coerced_confidence_parameter_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """coerced_confidence parameter controls the coerce function's confidence."""
    captured: dict[str, Any] = {}

    async def _fake(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"answers": ["go"], "confidence": 0.8, "defer": False, "rationale": "ok"}

    monkeypatch.setattr(veritas_impl, "ainvoke_structured_traced", _fake)
    await answer(_request(), model=object(), coerced_confidence=0.85)
    # The normalize lambda captured the coerced_confidence; verify it was forwarded.
    normalize_fn = captured.get("normalize")
    assert normalize_fn is not None
    raw = {"answers": ["go"]}
    normalized = normalize_fn(raw)
    assert normalized["confidence"] == 0.85
