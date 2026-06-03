"""Unit tests for plan subagent engine (RFC-618)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from soothe.subagents.plan import engine as plan_engine
from soothe.subagents.plan.engine import build_plan_engine
from soothe.subagents.plan.schemas import (
    CollectorDecision,
    PlanRefinement,
    PlanSubagentConfig,
)


def _patch_structured(
    monkeypatch: pytest.MonkeyPatch,
    *,
    collector_returns: list[CollectorDecision] | CollectorDecision,
    planner_returns: list[PlanRefinement] | PlanRefinement,
) -> dict[str, list[Any]]:
    """Patch invoke_structured_chat_typed with deterministic schema-typed answers."""
    collector_seq: list[CollectorDecision] = (
        list(collector_returns) if isinstance(collector_returns, list) else [collector_returns]
    )
    planner_seq: list[PlanRefinement] = (
        list(planner_returns) if isinstance(planner_returns, list) else [planner_returns]
    )
    calls: dict[str, list[Any]] = {"collector": [], "planner": []}

    async def _fake(_model: Any, messages: Any, schema: type[Any]) -> Any:
        if schema is CollectorDecision:
            calls["collector"].append(messages)
            return collector_seq.pop(0) if len(collector_seq) > 1 else collector_seq[0]
        if schema is PlanRefinement:
            calls["planner"].append(messages)
            return planner_seq.pop(0) if len(planner_seq) > 1 else planner_seq[0]
        raise AssertionError(f"unexpected schema: {schema}")

    monkeypatch.setattr(plan_engine, "invoke_structured_chat_typed", _fake)
    return calls


@pytest.mark.asyncio
async def test_plan_engine_skips_collection_when_explore_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When enable_explore is false, ingest routes to plan; explore is never invoked."""
    calls = _patch_structured(
        monkeypatch,
        collector_returns=CollectorDecision(
            explore_tasks=[], finish_collection=True, rationale="n/a"
        ),
        planner_returns=PlanRefinement(plan_markdown="# Plan\nDone.", finish_planning=True),
    )

    explore = MagicMock()
    explore.ainvoke = AsyncMock()

    graph = build_plan_engine(
        MagicMock(),
        explore,
        PlanSubagentConfig(enable_explore=False),
    )
    out = await graph.ainvoke({"messages": [HumanMessage(content="parent task")]})

    explore.ainvoke.assert_not_called()
    assert calls["collector"] == []
    assert "Plan" in out["messages"][-1].content


@pytest.mark.asyncio
async def test_plan_engine_collection_then_plan_invokes_explore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collection round runs explore tasks; planner produces final markdown."""
    _patch_structured(
        monkeypatch,
        collector_returns=CollectorDecision(
            explore_tasks=["locate pyproject.toml"],
            rationale="need layout",
            finish_collection=True,
        ),
        planner_returns=PlanRefinement(plan_markdown="# Final\nSteps here.", finish_planning=True),
    )

    explore = MagicMock()
    explore.ainvoke = AsyncMock(
        return_value={"messages": [AIMessage(content="found: pyproject.toml")]}
    )

    graph = build_plan_engine(
        MagicMock(),
        explore,
        PlanSubagentConfig(
            enable_explore=True,
            max_explore_passes=4,
            max_collection_rounds=3,
        ),
    )
    await graph.ainvoke({"messages": [HumanMessage(content="parent task")]})

    assert explore.ainvoke.await_count >= 1


@pytest.mark.asyncio
async def test_plan_engine_multi_round_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two collection iterations can each invoke explore before planning."""
    calls = _patch_structured(
        monkeypatch,
        collector_returns=[
            CollectorDecision(explore_tasks=["first"], finish_collection=False),
            CollectorDecision(explore_tasks=["second"], finish_collection=True),
        ],
        planner_returns=PlanRefinement(plan_markdown="# Out", finish_planning=True),
    )
    explore = MagicMock()
    explore.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content="ok")]})

    graph = build_plan_engine(
        MagicMock(),
        explore,
        PlanSubagentConfig(
            enable_explore=True,
            max_explore_passes=8,
            max_collection_rounds=5,
        ),
    )
    await graph.ainvoke({"messages": [HumanMessage(content="task")]})

    assert len(calls["collector"]) == 2
    assert explore.ainvoke.await_count == 2
