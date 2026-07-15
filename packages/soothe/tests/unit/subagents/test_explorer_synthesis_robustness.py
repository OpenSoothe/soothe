"""Explorer synthesis robustness tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from soothe.config import SootheConfig
from soothe.subagents.explore.middleware import ExplorePromptBudgetMiddleware
from soothe.subagents.explore.normalize import coerce_explore_result_dict
from soothe.subagents.explore.schemas import ExploreResult, ExploreSubagentConfig
from soothe.utils.llm.structured import StructuredOutputError


def test_coerce_explore_result_dict_normalizes_alias_and_required_fields() -> None:
    payload = {
        "target": "",
        "items": [
            {"file": "src/a.py", "summary": "alpha"},
            {"path": "src/b.py", "relevance": "critical", "description": "beta"},
        ],
        "summary": "",
    }
    out = coerce_explore_result_dict(
        payload,
        search_target="find parser",
        thoroughness="quick",
        max_matches=5,
    )

    assert out["target"] == "find parser"
    assert isinstance(out["matches"], list)
    assert len(out["matches"]) == 2
    assert out["matches"][0]["path"] == "src/a.py"
    assert out["matches"][0]["description"] == "alpha"
    assert out["matches"][1]["relevance"] == "medium"
    assert out["summary"]
    assert "suggested_next_actions" in out
    assert "coverage_gaps" in out
    assert "architecture_notes" in out


@pytest.mark.asyncio
async def test_async_synthesis_retries_after_structured_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _PolicyConfig:
        def model_copy(self, update: dict[str, Any]) -> _PolicyConfig:
            _ = update
            return self

    attempts = {"count": 0, "saw_repair_hint": False}

    async def _fake_structured(
        _model: Any,
        messages: list[Any],
        _schema: type[ExploreResult],
        *,
        normalize=None,
    ) -> ExploreResult:
        attempts["count"] += 1
        if len(messages) > 1 and "Structured output repair" in str(messages[-1].content):
            attempts["saw_repair_hint"] = True
        if attempts["count"] == 1:
            raise StructuredOutputError(
                "structured_output_validation_failed: 'matches' is required"
            )
        data = {"target": "", "items": [{"file": "x.py", "summary": "desc"}], "summary": ""}
        normalized = normalize(data) if callable(normalize) else data
        return ExploreResult.model_validate(normalized)

    async def _fake_await_with_policy(call, config=None):  # type: ignore[no-untyped-def]
        _ = config
        return await call()

    monkeypatch.setattr(
        "soothe.utils.llm.invoke_policy.llm_rate_limit_config_from",
        lambda _cfg: _PolicyConfig(),
    )
    monkeypatch.setattr(
        "soothe.utils.llm.invoke_policy.await_with_llm_call_policy",
        _fake_await_with_policy,
    )
    monkeypatch.setattr(
        "soothe.subagents.explore.middleware.invoke_structured_chat_typed",
        _fake_structured,
    )

    middleware = ExplorePromptBudgetMiddleware(
        model=SimpleNamespace(name="primary"),
        explore_config=ExploreSubagentConfig(
            synthesis_validation_retries=1,
            synthesis_fallback_to_primary_model=False,
        ),
        resolver_workspace="/tmp",
        max_iterations=5,
        max_matches=5,
        synthesis_model=SimpleNamespace(name="fast"),
        soothe_config=SootheConfig(),
    )

    result = await middleware._invoke_synthesis_llm_async("prompt", search_target="target")
    assert result.matches
    assert attempts["count"] == 2
    assert attempts["saw_repair_hint"] is True


@pytest.mark.asyncio
async def test_async_synthesis_falls_back_to_primary_model(monkeypatch: pytest.MonkeyPatch) -> None:
    class _PolicyConfig:
        def model_copy(self, update: dict[str, Any]) -> _PolicyConfig:
            _ = update
            return self

    primary = SimpleNamespace(name="primary")
    fast = SimpleNamespace(name="fast")
    attempts = {"fast": 0, "primary": 0}

    async def _fake_structured(
        model: Any,
        _messages: list[Any],
        _schema: type[ExploreResult],
        *,
        normalize=None,
    ) -> ExploreResult:
        if model is fast:
            attempts["fast"] += 1
            raise StructuredOutputError(
                "structured_output_validation_failed: 'matches' is required"
            )
        attempts["primary"] += 1
        data = {
            "target": "",
            "matches": [{"path": "a.py", "description": "a", "relevance": "high"}],
            "summary": "ok",
        }
        normalized = normalize(data) if callable(normalize) else data
        return ExploreResult.model_validate(normalized)

    async def _fake_await_with_policy(call, config=None):  # type: ignore[no-untyped-def]
        _ = config
        return await call()

    monkeypatch.setattr(
        "soothe.utils.llm.invoke_policy.llm_rate_limit_config_from",
        lambda _cfg: _PolicyConfig(),
    )
    monkeypatch.setattr(
        "soothe.utils.llm.invoke_policy.await_with_llm_call_policy",
        _fake_await_with_policy,
    )
    monkeypatch.setattr(
        "soothe.subagents.explore.middleware.invoke_structured_chat_typed",
        _fake_structured,
    )

    middleware = ExplorePromptBudgetMiddleware(
        model=primary,
        explore_config=ExploreSubagentConfig(
            synthesis_validation_retries=0,
            synthesis_fallback_to_primary_model=True,
        ),
        resolver_workspace="/tmp",
        max_iterations=5,
        max_matches=5,
        synthesis_model=fast,
        soothe_config=SootheConfig(),
    )

    result = await middleware._invoke_synthesis_llm_async("prompt", search_target="target")
    assert result.summary == "ok"
    assert attempts["fast"] == 1
    assert attempts["primary"] == 1
