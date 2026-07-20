"""Unit tests for plan subagent engine (RFC-618)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage

from soothe_nano.subagents.plan import engine as plan_engine
from soothe_nano.subagents.plan.engine import build_plan_engine
from soothe_nano.subagents.plan.schemas import PlanRefinement, PlanSubagentConfig


def _patch_planner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    planner_returns: list[PlanRefinement] | PlanRefinement,
) -> list[Any]:
    planner_seq: list[PlanRefinement] = (
        list(planner_returns) if isinstance(planner_returns, list) else [planner_returns]
    )
    calls: list[Any] = []

    async def _fake(_model: Any, messages: Any, schema: type[Any]) -> Any:
        if schema is PlanRefinement:
            calls.append(messages)
            return planner_seq.pop(0) if len(planner_seq) > 1 else planner_seq[0]
        raise AssertionError(f"unexpected schema: {schema}")

    monkeypatch.setattr(plan_engine, "invoke_structured_chat_typed", _fake)
    return calls


@pytest.mark.asyncio
async def test_plan_engine_produces_markdown_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan subagent runs plan-design loop and returns markdown."""
    calls = _patch_planner(
        monkeypatch,
        planner_returns=PlanRefinement(plan_markdown="# Plan\nDone.", finish_planning=True),
    )

    graph = build_plan_engine(MagicMock(), PlanSubagentConfig())
    out = await graph.ainvoke({"messages": [HumanMessage(content="parent task")]})

    assert len(calls) == 1
    assert "Plan" in out["messages"][-1].content


@pytest.mark.asyncio
async def test_plan_engine_multi_round_refinement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multiple plan rounds run before finish."""
    calls = _patch_planner(
        monkeypatch,
        planner_returns=[
            PlanRefinement(plan_markdown="# Draft", finish_planning=False),
            PlanRefinement(plan_markdown="# Final", finish_planning=True),
        ],
    )

    graph = build_plan_engine(MagicMock(), PlanSubagentConfig(max_plan_rounds=5))
    out = await graph.ainvoke({"messages": [HumanMessage(content="task")]})

    assert len(calls) == 2
    assert "Final" in out["messages"][-1].content
