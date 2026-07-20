"""Explorer synthesis robustness tests."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from soothe_nano.config import SootheConfig
from soothe_nano.subagents.explore.middleware import (
    ExploreFinalizeMiddleware,
    ExploreFindingsMiddleware,
    ExplorePromptBudgetMiddleware,
)
from soothe_nano.subagents.explore.normalize import coerce_explore_result_dict
from soothe_nano.subagents.explore.schemas import ExploreResult, ExploreSubagentConfig
from soothe_nano.utils.llm.structured import StructuredOutputError


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
        "soothe_nano.utils.llm.invoke_policy.llm_rate_limit_config_from",
        lambda _cfg: _PolicyConfig(),
    )
    monkeypatch.setattr(
        "soothe_nano.utils.llm.invoke_policy.await_with_llm_call_policy",
        _fake_await_with_policy,
    )
    monkeypatch.setattr(
        "soothe_nano.subagents.explore.middleware.invoke_structured_chat_typed",
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
        "soothe_nano.utils.llm.invoke_policy.llm_rate_limit_config_from",
        lambda _cfg: _PolicyConfig(),
    )
    monkeypatch.setattr(
        "soothe_nano.utils.llm.invoke_policy.await_with_llm_call_policy",
        _fake_await_with_policy,
    )
    monkeypatch.setattr(
        "soothe_nano.subagents.explore.middleware.invoke_structured_chat_typed",
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


@pytest.mark.asyncio
async def test_awrap_model_call_early_stops_on_stalled_findings() -> None:
    middleware = ExplorePromptBudgetMiddleware(
        model=SimpleNamespace(name="primary"),
        explore_config=ExploreSubagentConfig(early_stop_no_new_findings_turns=2),
        resolver_workspace="/tmp",
        max_iterations=10,
        max_matches=5,
        soothe_config=SootheConfig(),
    )
    state = {
        "search_target": "find parser",
        "findings": [{"path": "src/parser.py", "snippet": None, "relevance": "unknown"}],
        "prev_findings_count": 1,
        "findings_stall_counter": 1,
        "explore_model_invocations": 1,
    }
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[HumanMessage(content="find parser")],
        state=state,
    )

    async def _handler(_request: ModelRequest[None]) -> ModelResponse:
        return ModelResponse(result=[AIMessage(content="should not execute")])

    async def _fake_synthesize(
        _findings: list[dict[str, Any]],
        _search_target: str,
        _current_iter: int,
        *,
        failure_reason: str = "",
    ) -> ModelResponse:
        _ = failure_reason
        return ModelResponse(result=[AIMessage(content="early-stop")])

    middleware._asynthesize_findings = _fake_synthesize  # type: ignore[method-assign]
    result = await middleware.awrap_model_call(request, _handler)
    assert isinstance(result, ModelResponse)
    assert "early-stop" in str(result.result[0].content)


def test_findings_merge_dedupes_duplicate_rows() -> None:
    middleware = ExploreFindingsMiddleware()
    request = ToolCallRequest(
        tool_call={"name": "ls", "args": {"path": "/repo"}, "id": "functions.ls:1"},
        tool=None,
        state={
            "messages": [],
            "findings": [{"path": "/repo/src", "snippet": None, "relevance": "unknown"}],
        },
        runtime=None,
    )

    def _handler(_request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content="/repo/src\n/repo/tests",
            tool_call_id="functions.ls:1",
            name="ls",
        )

    result = middleware.wrap_tool_call(request, _handler)
    assert hasattr(result, "update")
    update = getattr(result, "update")
    assert "findings" in update
    assert update["findings"] == [{"path": "/repo/tests", "snippet": None, "relevance": "unknown"}]


def test_finalize_uses_explore_start_time_for_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _capture(event: dict[str, Any], _logger: Any) -> None:
        captured.update(event)

    monkeypatch.setattr(
        "soothe_nano.subagents.explore.middleware.emit_subagent_wire_event", _capture
    )
    middleware = ExploreFinalizeMiddleware(thoroughness="medium", max_matches=5)
    result = ExploreResult(
        target="find parser",
        matches=[{"path": "src/parser.py", "relevance": "high", "description": "Parser entry"}],
        summary="Found parser entry point.",
    )
    state = {
        "messages": [HumanMessage(content="find parser")],
        "structured_response": result,
        "findings": [{"path": "src/parser.py", "snippet": None, "relevance": "unknown"}],
        "explore_model_invocations": 2,
        "explore_started_at_monotonic": time.perf_counter() - 1.5,
    }

    updates = middleware.after_agent(state=state, runtime=None)
    assert updates is not None
    assert captured.get("duration_ms", 0) >= 1000


def test_coerce_explore_result_keeps_original_search_target() -> None:
    out = coerce_explore_result_dict(
        {
            "target": "LLM rewrote target with verbose instructions",
            "matches": [],
            "summary": "",
        },
        search_target="use explorer to analyze project arch",
        thoroughness="medium",
        max_matches=5,
    )
    assert out["target"] == "use explorer to analyze project arch"


def test_sync_synthesis_quality_gate_replaces_empty_matches_with_deterministic_complete() -> None:
    middleware = ExplorePromptBudgetMiddleware(
        model=SimpleNamespace(name="primary"),
        explore_config=ExploreSubagentConfig(),
        resolver_workspace="/tmp",
        max_iterations=10,
        max_matches=5,
        soothe_config=SootheConfig(),
    )
    middleware._invoke_synthesis_llm_sync = lambda *_args, **_kwargs: ExploreResult(  # type: ignore[method-assign]
        target="bad target",
        matches=[],
        summary="",
    )
    findings = [{"path": "packages/soothe/src/soothe/subagents/explore/middleware.py"}]
    response = middleware._synthesize_findings(
        findings=findings,
        search_target="use explorer to analyze project arch",
        current_iter=3,
    )
    structured = response.model_response.structured_response
    assert isinstance(structured, ExploreResult)
    assert structured.matches
    assert structured.target == "use explorer to analyze project arch"
    assert response.command.update["explore_completion_status"] == "complete"
