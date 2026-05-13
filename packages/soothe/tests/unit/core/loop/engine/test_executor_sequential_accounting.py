"""Executor sequential waves: one StepResult per StepAction (scheme B), chunked by max_parallel_steps."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from soothe.core.loop.engine.executor import Executor
from soothe.core.loop.state.schemas import (
    AgentDecision,
    LoopState,
    StepAction,
    StepResult,
)


async def _empty_agent_stream() -> None:
    if False:
        yield None  # pragma: no cover — makes this an async generator


@pytest.mark.asyncio
async def test_sequential_single_wave_yields_one_result_per_step() -> None:
    mock_agent = MagicMock()
    mock_agent.astream = MagicMock(side_effect=lambda *a, **k: _empty_agent_stream())

    executor = Executor(mock_agent, max_parallel_steps=4)
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="a", description="first", expected_output="o1"),
            StepAction(id="b", description="second", expected_output="o2"),
        ],
        execution_mode="sequential",
        reasoning="r",
    )
    state = LoopState(goal="g", thread_id="t-main")
    out = [x async for x in executor.execute(decision, state) if isinstance(x, StepResult)]

    assert len(out) == 2
    assert {r.step_id for r in out} == {"a", "b"}
    assert all(r.success for r in out)
    assert mock_agent.astream.call_count == 1


@pytest.mark.asyncio
async def test_sequential_respects_max_parallel_steps_multiple_waves() -> None:
    mock_agent = MagicMock()
    mock_agent.astream = MagicMock(side_effect=lambda *a, **k: _empty_agent_stream())

    executor = Executor(mock_agent, max_parallel_steps=1)
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="a", description="first", expected_output="o1"),
            StepAction(id="b", description="second", expected_output="o2"),
        ],
        execution_mode="sequential",
        reasoning="r",
    )
    state = LoopState(goal="g", thread_id="t-main")
    out = [x async for x in executor.execute(decision, state) if isinstance(x, StepResult)]

    assert len(out) == 2
    assert mock_agent.astream.call_count == 2


@pytest.mark.asyncio
async def test_sequential_plan_with_dependencies_drains_ready_chain() -> None:
    mock_agent = MagicMock()
    mock_agent.astream = MagicMock(side_effect=lambda *a, **k: _empty_agent_stream())

    executor = Executor(mock_agent, max_parallel_steps=4)
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="01", description="discover files", expected_output="files"),
            StepAction(
                id="02",
                description="read files",
                expected_output="content",
                dependencies=["01"],
            ),
            StepAction(
                id="03",
                description="validate refs",
                expected_output="report",
                dependencies=["02"],
            ),
        ],
        execution_mode="sequential",
        reasoning="r",
    )
    state = LoopState(goal="g", thread_id="t-main")

    out = [x async for x in executor.execute(decision, state) if isinstance(x, StepResult)]

    assert [r.step_id for r in out] == ["01", "02", "03"]
    assert mock_agent.astream.call_count == 3


def test_extract_sequential_outcomes_single_step_fills_ledger_from_chunks_ig373() -> None:
    """Trailing empty AIMessage after chunks must not produce empty LoopAIMessage content (IG-373)."""
    mock_agent = MagicMock()
    executor = Executor(mock_agent, max_parallel_steps=4)
    state = LoopState(goal="g", thread_id="tid", iteration=0, max_iterations=8)
    steps = [StepAction(id="9oi", description="read readme top", expected_output="lines")]
    messages: list = [
        AIMessageChunk(content="Here are the first lines:\n"),
        AIMessageChunk(content="A\nB\n"),
        AIMessage(content=""),
    ]
    outcomes = executor._extract_sequential_outcomes(messages, steps, state)
    assert "9oi" in outcomes
    body = outcomes["9oi"].content
    assert "Here are the first lines" in body
    assert "A\nB" in body


@pytest.mark.asyncio
async def test_parallel_waves_respect_max_parallel_steps() -> None:
    mock_agent = MagicMock()
    mock_agent.astream = MagicMock(side_effect=lambda *a, **k: _empty_agent_stream())

    executor = Executor(mock_agent, max_parallel_steps=1)
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="a", description="p1", expected_output="o"),
            StepAction(id="b", description="p2", expected_output="o"),
        ],
        execution_mode="parallel",
        reasoning="r",
    )
    state = LoopState(goal="g", thread_id="t-main")
    async for _ in executor.execute(decision, state):
        pass

    assert mock_agent.astream.call_count == 2
