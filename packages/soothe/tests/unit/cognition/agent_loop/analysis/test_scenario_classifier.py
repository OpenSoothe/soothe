"""Unit tests for scenario classifier response parsing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from soothe.cognition.agent_loop.analysis.scenario_classifier import (
    ScenarioClassification,
    classify_synthesis_scenario,
)


class _StubStepResult:
    def __init__(self, success: bool = True) -> None:
        self.success = success
        self.outcome = {"type": "tool", "tool_name": "glob"}

    def to_evidence_string(self, truncate: bool = False) -> str:  # noqa: ARG002
        return "evidence"


class _StubLLM:
    def __init__(self, content: object) -> None:
        self._content = content

    async def ainvoke(self, _messages: list[object]) -> object:
        return SimpleNamespace(content=self._content)


def _build_state() -> SimpleNamespace:
    return SimpleNamespace(
        intent=SimpleNamespace(intent_type="new_goal", task_complexity="medium"),
        step_results=[_StubStepResult()],
    )


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

    result = await classify_synthesis_scenario("count readmes", _build_state(), llm)
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

    result = await classify_synthesis_scenario("count readmes", _build_state(), llm)
    assert result.scenario == "general_summary"
    assert result.contextual_focus[0] == "Count by package"


@pytest.mark.asyncio
async def test_classify_scenario_falls_back_on_invalid_response() -> None:
    llm = _StubLLM("not json at all")

    result = await classify_synthesis_scenario("count readmes", _build_state(), llm)
    assert result.scenario == "general_summary"
    assert result.sections == ["Summary", "Key Points"]
