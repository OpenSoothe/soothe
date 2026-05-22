"""Executor per-step tool call budget wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage

from soothe.core.loop.engine.executor import (
    _DEFAULT_MAX_TOOL_CALLS_PER_STEP,
    Executor,
    _ActStreamBudget,
)
from soothe.core.loop.state.schemas import AgentDecision, LoopState, StepAction, StepResult


def _make_step() -> StepAction:
    return StepAction(
        id="s0",
        description="Run tools",
        subagent=None,
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

    ex = Executor(MagicMock(), max_parallel_steps=1)
    rows = [
        r
        async for r in ex._stream_and_collect(fake_stream(), budget=budget, step_id="s0")
        if r[0] is not None
    ]

    assert len(rows) == 1
    output, _, tool_count, _msgs, _df, outcomes = rows[0]
    assert tool_count == 2
    assert budget.hit_tool_budget is True
    assert "alpha" in output and "beta" in output
    assert "gamma" not in output
    assert len(outcomes) == 2


def test_default_max_tool_calls_per_step_is_99() -> None:
    assert _DEFAULT_MAX_TOOL_CALLS_PER_STEP == 99
    assert Executor._max_tool_calls_per_step() == 99


@pytest.mark.asyncio
async def test_execute_parallel_step_returns_partial_on_tool_budget() -> None:
    agent = MagicMock()
    tool_msgs = [
        (
            (),
            "messages",
            (ToolMessage(content=f"out-{i}", tool_call_id=str(i), name="run_command"), {}),
        )
        for i in range(_DEFAULT_MAX_TOOL_CALLS_PER_STEP + 5)
    ]

    async def fake_astream(*_a: object, **_k: object):
        for c in tool_msgs:
            yield c

    agent.astream = fake_astream

    ex = Executor(agent, max_parallel_steps=1, config=None)
    state = LoopState(goal="g", thread_id="t", max_iterations=3)
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
    ledger_ai = [m for m in state.loop_messages if getattr(m, "step_id", None) == "s0"][-1]
    assert "Step execution failed" not in ledger_ai.content
