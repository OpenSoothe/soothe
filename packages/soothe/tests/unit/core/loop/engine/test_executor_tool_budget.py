"""Executor per-step tool call budget wiring."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import ToolMessage

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.foundation.sloop.engine.executor import (
    _DEFAULT_MAX_TOOL_CALLS_PER_STEP,
    Executor,
    _ActStreamBudget,
)
from soothe.foundation.sloop.engine.graph_interrupt import DispatchTimeoutError
from soothe.foundation.sloop.state.schemas import AgentDecision, LoopState, StepAction, StepResult


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with sqlite :memory: backend for tests."""
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


def _make_step() -> StepAction:
    return StepAction(
        id="s0",
        description="Run tools",
        expected_output="ok",
        dependencies=[],
    )


@pytest.mark.asyncio
async def test_stream_stops_after_tool_budget_with_partial_outcomes() -> None:
    budget = _ActStreamBudget(max_tool_calls_per_step=2)
    chunks: list = [
        ((), "messages", (ToolMessage(content="alpha", tool_call_id="1", name="grep"), {})),
        ((), "messages", (ToolMessage(content="beta", tool_call_id="2", name="grep"), {})),
        ((), "messages", (ToolMessage(content="gamma", tool_call_id="3", name="grep"), {})),
    ]

    async def fake_stream():
        for c in chunks:
            yield c

    ex = Executor(MagicMock(), max_parallel_steps=1, context_engine=_make_ce())
    rows = [
        r
        async for r in ex._stream_and_collect(fake_stream(), budget=budget, step_id="s0")
        if r.output is not None
    ]

    assert len(rows) == 1
    final = rows[0]
    assert final.main_tool_count == 2
    assert budget.hit_tool_budget is True
    assert "alpha" in (final.output or "") and "beta" in (final.output or "")
    assert "gamma" not in (final.output or "")
    assert len(final.outcomes) == 2


def test_default_max_tool_calls_per_step_is_999() -> None:
    assert _DEFAULT_MAX_TOOL_CALLS_PER_STEP == 999
    assert (
        Executor(
            MagicMock(), max_parallel_steps=1, context_engine=_make_ce()
        )._max_tool_calls_per_step()
        == 999
    )


def test_max_tool_calls_per_step_reads_loop_config() -> None:
    config = MagicMock()
    config.agent.loop.max_tool_calls_per_step = 42
    ex = Executor(
        MagicMock(),
        max_parallel_steps=1,
        config=config,
        context_engine=_make_ce(),
    )
    assert ex._max_tool_calls_per_step() == 42


def _make_mock_agent(chunks: list) -> MagicMock:
    async def fake_execution_astream(*_a: object, **_k: object) -> AsyncIterator[Any]:
        for c in chunks:
            yield c

    agent = MagicMock()
    agent.execution_astream = MagicMock(side_effect=fake_execution_astream)
    agent.execution_aget_state = AsyncMock(return_value=MagicMock())
    agent.aget_state = AsyncMock(return_value=MagicMock())
    return agent


@pytest.mark.asyncio
async def test_execute_parallel_step_returns_partial_on_tool_budget() -> None:
    tool_msgs = [
        (
            (),
            "messages",
            (ToolMessage(content=f"out-{i}", tool_call_id=str(i), name="run_command"), {}),
        )
        for i in range(_DEFAULT_MAX_TOOL_CALLS_PER_STEP + 5)
    ]
    agent = _make_mock_agent(tool_msgs)

    ce = _make_ce()
    ex = Executor(agent, max_parallel_steps=1, config=None, context_engine=ce)
    state = LoopState(goal="g", thread_id="t", max_iterations=3)
    goal = GoalNode(description="test")
    ce._dag.add_goal(goal)
    state.bind_ce(ce, goal.id)
    step = _make_step()

    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="",
    )
    out = [item async for item in ex.execute(decision, state)]

    results = [x for x in out if isinstance(x, StepResult)]
    assert len(results) == 1
    sr = results[0]
    assert sr.hit_tool_budget is True
    assert sr.tool_call_count == _DEFAULT_MAX_TOOL_CALLS_PER_STEP
    assert sr.success is True
    assert state.last_wave_hit_tool_budget is True
    preview = sr.outcome.get("wave_join_preview") or sr.outcome.get("output_summary") or ""
    if isinstance(preview, dict):
        preview = str(preview.get("first", ""))
    assert "out-0" in str(preview)
    ledger_ai = [m for m in ce.ledger.get_messages() if getattr(m, "step_id", None) == "s0"][-1]
    assert "Step execution failed" not in ledger_ai.content


@pytest.mark.asyncio
async def test_stream_collect_exposes_execution_metrics() -> None:
    budget = _ActStreamBudget(max_tool_calls_per_step=8)
    chunks = [
        (
            (),
            "messages",
            (ToolMessage(content="x.py:12:needle", tool_call_id="1", name="grep"), {}),
        ),
        (
            (),
            "messages",
            (
                ToolMessage(
                    content="1|line one\n2|line two",
                    tool_call_id="2",
                    name="read_file",
                ),
                {},
            ),
        ),
    ]

    async def fake_stream():
        for c in chunks:
            yield c

    ex = Executor(MagicMock(), max_parallel_steps=1, context_engine=_make_ce())
    rows = [
        r
        async for r in ex._stream_and_collect(fake_stream(), budget=budget, step_id="s0")
        if r.output is not None
    ]
    assert len(rows) == 1
    final = rows[0]
    assert final.execution_metrics.get("search_calls_total") == 1
    assert final.execution_metrics.get("evidence_reads_total") == 1


@pytest.mark.asyncio
async def test_stream_collect_no_progress_watchdog_raises_timeout() -> None:
    config = MagicMock()
    config.agent.loop.dispatch_timeout_seconds = 0.01
    config.agent.loop.max_tool_calls_per_step = 999

    async def fake_stream():
        yield ((), "custom", {"kind": "heartbeat"})
        await asyncio.sleep(0.03)
        yield ((), "custom", {"kind": "heartbeat"})

    ex = Executor(MagicMock(), max_parallel_steps=1, context_engine=_make_ce(), config=config)
    with pytest.raises(DispatchTimeoutError):
        async for _ in ex._stream_and_collect(
            fake_stream(),
            budget=_ActStreamBudget(max_tool_calls_per_step=10),
            step_id="s_watchdog",
        ):
            pass
