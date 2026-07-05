"""Unit tests for scenario classifier heuristic + LLM response parsing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from soothe.foundation.sloop.engine.scenario_classifier import (
    ScenarioClassification,
    _extract_execution_summary,
    _heuristic_classify,
    classify_synthesis_scenario,
)


class _StubStepResult:
    def __init__(
        self, success: bool = True, outcome_type: str = "tool", tool_name: str = "glob"
    ) -> None:
        self.success = success
        self.outcome = {"type": outcome_type, "tool_name": tool_name}

    def to_evidence_string(self, truncate: bool = False) -> str:  # noqa: ARG002
        return "evidence" * 200  # ~1600 chars per step


class _StubLLM:
    def __init__(self, content: object) -> None:
        self._content = content

    async def ainvoke(self, _messages: list[object], **_kwargs: object) -> object:
        return SimpleNamespace(content=self._content)


def _build_state(
    step_count: int = 1,
    all_success: bool = True,
    task_complexity: str = "medium",
) -> SimpleNamespace:
    results = []
    for i in range(step_count):
        results.append(
            _StubStepResult(success=all_success, outcome_type="tool" if i % 2 == 0 else "llm_call")
        )
    return SimpleNamespace(
        intent=SimpleNamespace(task_complexity=task_complexity),
        step_results=results,
    )


# ── Heuristic fast-path tests ──────────────────────────────────────────


def test_heuristic_single_step_returns_general_summary() -> None:
    summary = {
        "total_steps": 1,
        "successful_steps": 1,
        "step_types": ["tool"],
        "tools_used": ["glob"],
        "evidence_volume": 1600,
    }
    result = _heuristic_classify("count readmes", "agentic", summary)
    assert result is not None
    assert result.scenario == "general_summary"


def test_heuristic_zero_successful_steps_returns_investigation() -> None:
    summary = {
        "total_steps": 3,
        "successful_steps": 0,
        "step_types": ["tool", "tool", "tool"],
        "tools_used": ["glob"],
        "evidence_volume": 4800,
    }
    result = _heuristic_classify("fix the build", "agentic", summary)
    assert result is not None
    assert result.scenario == "investigation_summary"


def test_heuristic_many_steps_with_tools_returns_analysis() -> None:
    summary = {
        "total_steps": 5,
        "successful_steps": 4,
        "step_types": ["tool", "llm_call", "tool", "tool", "tool"],
        "tools_used": ["glob", "grep"],
        "evidence_volume": 8000,
    }
    result = _heuristic_classify("analyze the codebase", "agentic", summary)
    assert result is not None
    assert result.scenario == "analysis_report"


def test_heuristic_low_evidence_returns_general() -> None:
    summary = {
        "total_steps": 2,
        "successful_steps": 2,
        "step_types": ["llm_call", "llm_call"],
        "tools_used": [],
        "evidence_volume": 500,
    }
    result = _heuristic_classify("summarize this", "agentic", summary)
    assert result is not None
    assert result.scenario == "general_summary"


def test_heuristic_ambiguous_returns_none() -> None:
    # 3 steps, mixed success, tool usage, decent evidence → not caught by any rule
    summary = {
        "total_steps": 3,
        "successful_steps": 2,
        "step_types": ["tool", "llm_call", "tool"],
        "tools_used": ["glob"],
        "evidence_volume": 5000,
    }
    result = _heuristic_classify("refactor the module", "agentic", summary)
    assert result is None  # falls through to LLM


# ── _extract_execution_summary tests ───────────────────────────────────


def test_extract_execution_summary_from_state() -> None:
    state = _build_state(step_count=3)
    summary = _extract_execution_summary(state)
    assert summary["total_steps"] == 3
    assert summary["successful_steps"] == 3
    assert len(summary["step_types"]) == 3
    assert summary["evidence_volume"] > 0


# ── LLM path tests (use state that bypasses heuristic) ─────────────────


@pytest.mark.asyncio
async def test_classify_scenario_accepts_raw_json_response() -> None:
    llm = _StubLLM(
        """{
  "scenario": "general_summary",
  "sections": ["Summary", "Key Points"],
  "contextual_focus": ["Focus area A", "Focus area B"],
  "evidence_emphasis": "Use available evidence"
}"""
    )
    # 3-step state → heuristic returns None, falls through to LLM
    result = await classify_synthesis_scenario("count readmes", _build_state(step_count=3), llm)
    assert isinstance(result, ScenarioClassification)
    assert result.scenario == "general_summary"
    assert result.sections == ["Summary", "Key Points"]


@pytest.mark.asyncio
async def test_classify_scenario_accepts_fenced_json_response() -> None:
    llm = _StubLLM(
        """```json
{
  "scenario": "general_summary",
  "sections": ["Summary", "Key Points"],
  "contextual_focus": ["Count by package", "Highlight totals"],
  "evidence_emphasis": "Reference file discovery evidence"
}
```"""
    )
    # 3-step state → heuristic returns None, falls through to LLM
    result = await classify_synthesis_scenario("count readmes", _build_state(step_count=3), llm)
    assert result.scenario == "general_summary"
    assert result.contextual_focus[0] == "Count by package"


@pytest.mark.asyncio
async def test_classify_scenario_falls_back_on_invalid_response() -> None:
    llm = _StubLLM("not json at all")
    # 3-step state → heuristic returns None, falls through to LLM → LLM fails → fallback
    result = await classify_synthesis_scenario("count readmes", _build_state(step_count=3), llm)
    assert result.scenario == "general_summary"
    assert result.sections == ["Summary", "Key Points"]


@pytest.mark.asyncio
async def test_heuristic_skips_llm_for_single_step() -> None:
    """Single-step state should never call the LLM (heuristic fast-path)."""
    # Use a broken LLM that would fail — if heuristic works, it won't be called
    llm = _StubLLM("THIS_WOULD_FAIL_IF_CALLED")
    result = await classify_synthesis_scenario("count readmes", _build_state(step_count=1), llm)
    assert result.scenario == "general_summary"
    assert result.contextual_focus[0].startswith("Summarize result for:")
