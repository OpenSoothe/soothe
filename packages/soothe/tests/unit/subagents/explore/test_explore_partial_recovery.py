"""Tests for explore partial-result recovery (synthesis failure, finalize, invoke)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from soothe.subagents.explore.middleware import (
    ExploreFinalizeMiddleware,
    ExplorePromptBudgetMiddleware,
)
from soothe.subagents.explore.partial import build_explore_result_from_findings
from soothe.subagents.explore.recovery import recover_explore_invoke_result
from soothe.subagents.explore.schemas import ExploreResult, ExploreSubagentConfig


def test_build_explore_result_from_findings_partial() -> None:
    findings = [
        {"path": "/a.py", "snippet": "class Foo", "relevance": "unknown"},
        {"path": "/b.py", "snippet": None, "relevance": "high"},
        {"path": "/a.py", "snippet": "dup"},
    ]
    result = build_explore_result_from_findings(
        findings,
        search_target="find Foo",
        thoroughness="medium",
        max_matches=5,
        status="partial",
        failure_reason="synthesis timed out",
    )
    assert result.target == "find Foo"
    assert len(result.matches) == 2
    assert result.matches[0].path == "/a.py"
    assert "partial" in result.summary.lower()
    assert "synthesis timed out" in result.coverage_gaps


def test_finalize_recovers_from_findings_without_structured_response() -> None:
    mw = ExploreFinalizeMiddleware(thoroughness="medium", max_matches=3)
    state = {
        "messages": [HumanMessage(content="find goal engine")],
        "findings": [{"path": "/goal.py", "snippet": "class Goal", "relevance": "unknown"}],
        "explore_model_invocations": 3,
    }
    with patch("soothe.subagents.explore.middleware.emit_subagent_wire_event") as emit:
        updates = mw.after_agent(state, None)
    assert updates is not None
    msgs = updates["messages"]
    assert isinstance(msgs.value[0], AIMessage)
    assert "Explore results" in str(msgs.value[0].content)
    assert updates.get("explore_completion_status") == "partial"
    emit.assert_called_once()
    payload = emit.call_args[0][0]
    assert payload["completion_status"] == "partial"


def test_finalize_failed_when_no_findings() -> None:
    mw = ExploreFinalizeMiddleware(thoroughness="quick", max_matches=2)
    with patch("soothe.subagents.explore.middleware.emit_subagent_wire_event") as emit:
        updates = mw.after_agent({"messages": [], "findings": []}, None)
    assert updates is not None
    assert "did not complete" in str(updates["messages"].value[0].content)
    emit.assert_called_once()
    assert emit.call_args[0][0]["completion_status"] == "failed"


def test_synthesize_findings_falls_back_on_llm_error() -> None:
    model = MagicMock()

    mw = ExplorePromptBudgetMiddleware(
        model=model,
        explore_config=ExploreSubagentConfig(enable_semantic_similarity=False),
        resolver_workspace="/tmp",
        max_iterations=10,
        max_matches=3,
        synthesis_model=model,
    )
    findings = [{"path": "/x.py", "snippet": "content", "relevance": "unknown"}]
    with patch.object(
        mw,
        "_invoke_synthesis_llm_sync",
        side_effect=RuntimeError("structured output failed"),
    ):
        response = mw._synthesize_findings(findings, "find x", 5)
    structured = response.model_response.structured_response
    assert structured is not None
    assert len(structured.matches) == 1
    assert response.command is not None
    update = response.command.update or {}
    assert update.get("explore_completion_status") == "partial"


def test_recover_explore_invoke_result_from_stream() -> None:
    inner = MagicMock()
    inner.stream.return_value = [
        {"findings": [{"path": "/z.py", "snippet": "z", "relevance": "unknown"}]},
    ]
    state = {"messages": [HumanMessage(content="find z")]}
    out = recover_explore_invoke_result(
        inner,
        state,
        None,
        RuntimeError("graph blew up"),
        thoroughness="medium",
        max_matches=2,
    )
    assert out["explore_completion_status"] == "partial"
    assert isinstance(out["structured_response"], ExploreResult)
    assert out["structured_response"].matches[0].path == "/z.py"


def test_recover_explore_invoke_result_reraises_without_findings() -> None:
    inner = MagicMock()
    inner.stream.return_value = [{}]
    with pytest.raises(RuntimeError, match="graph blew up"):
        recover_explore_invoke_result(
            inner,
            {"messages": []},
            None,
            RuntimeError("graph blew up"),
            thoroughness="medium",
            max_matches=2,
        )
