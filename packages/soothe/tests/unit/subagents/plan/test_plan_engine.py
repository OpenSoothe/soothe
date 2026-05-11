"""Unit tests for plan subagent engine (RFC-618)."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from soothe.subagents.plan.engine import build_plan_engine
from soothe.subagents.plan.schemas import (
    CollectorDecision,
    PlanRefinement,
    PlanSubagentConfig,
)


def test_plan_engine_skips_collection_when_explore_disabled() -> None:
    """When enable_explore is false, ingest routes to plan; explore is never invoked."""
    model = MagicMock()
    collector_m = MagicMock()
    planner_m = MagicMock()
    model.with_structured_output.side_effect = [collector_m, planner_m]
    planner_m.invoke.return_value = PlanRefinement(
        plan_markdown="# Plan\nDone.",
        finish_planning=True,
    )

    explore = MagicMock()

    graph = build_plan_engine(model, explore, PlanSubagentConfig(enable_explore=False))
    out = graph.invoke({"messages": [HumanMessage(content="parent task")]})

    explore.invoke.assert_not_called()
    collector_m.invoke.assert_not_called()
    assert "Plan" in out["messages"][-1].content


def test_plan_engine_collection_then_plan_invokes_explore() -> None:
    """Collection round runs explore tasks; planner produces final markdown."""
    model = MagicMock()
    collector_m = MagicMock()
    planner_m = MagicMock()
    model.with_structured_output.side_effect = [collector_m, planner_m]
    collector_m.invoke.return_value = CollectorDecision(
        explore_tasks=["locate pyproject.toml"],
        rationale="need layout",
        finish_collection=True,
    )
    planner_m.invoke.return_value = PlanRefinement(
        plan_markdown="# Final\nSteps here.",
        finish_planning=True,
    )

    explore = MagicMock()
    explore.invoke.return_value = {"messages": [AIMessage(content="found: pyproject.toml")]}

    graph = build_plan_engine(
        model,
        explore,
        PlanSubagentConfig(
            enable_explore=True,
            max_explore_passes=4,
            max_collection_rounds=3,
        ),
    )
    graph.invoke({"messages": [HumanMessage(content="parent task")]})

    assert explore.invoke.call_count >= 1


def test_plan_engine_multi_round_collection() -> None:
    """Two collection iterations can each invoke explore before planning."""
    model = MagicMock()
    collector_m = MagicMock()
    planner_m = MagicMock()
    model.with_structured_output.side_effect = [collector_m, planner_m]
    collector_m.invoke.side_effect = [
        CollectorDecision(explore_tasks=["first"], finish_collection=False),
        CollectorDecision(explore_tasks=["second"], finish_collection=True),
    ]
    planner_m.invoke.return_value = PlanRefinement(
        plan_markdown="# Out",
        finish_planning=True,
    )
    explore = MagicMock()
    explore.invoke.return_value = {"messages": [AIMessage(content="ok")]}

    graph = build_plan_engine(
        model,
        explore,
        PlanSubagentConfig(
            enable_explore=True,
            max_explore_passes=8,
            max_collection_rounds=5,
        ),
    )
    graph.invoke({"messages": [HumanMessage(content="task")]})

    assert collector_m.invoke.call_count == 2
    assert explore.invoke.call_count == 2
