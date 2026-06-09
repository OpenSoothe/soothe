"""Executor parallel waves: one StepResult per StepAction, chunked by max_parallel_steps."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from soothe.foundation.loop.engine.executor import Executor, StepWaveQueued, StepWaveStart
from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    LoopState,
    StepAction,
    StepResult,
)


async def _empty_agent_stream() -> None:
    if False:
        yield None  # pragma: no cover — makes this an async generator


@pytest.mark.asyncio
async def test_parallel_single_wave_yields_one_result_per_step() -> None:
    mock_agent = MagicMock()
    mock_agent.astream = MagicMock(side_effect=lambda *a, **k: _empty_agent_stream())

    executor = Executor(mock_agent, max_parallel_steps=4)
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="a", description="first", expected_output="o1"),
            StepAction(id="b", description="second", expected_output="o2"),
        ],
        execution_mode="parallel",
        reasoning="r",
    )
    state = LoopState(goal="g", thread_id="t-main")
    out = [x async for x in executor.execute(decision, state) if isinstance(x, StepResult)]

    assert len(out) == 2
    assert {r.step_id for r in out} == {"a", "b"}
    assert all(r.success for r in out)
    assert mock_agent.astream.call_count == 2


@pytest.mark.asyncio
async def test_parallel_respects_max_parallel_steps_multiple_waves() -> None:
    mock_agent = MagicMock()
    mock_agent.astream = MagicMock(side_effect=lambda *a, **k: _empty_agent_stream())

    executor = Executor(mock_agent, max_parallel_steps=1)
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="a", description="first", expected_output="o1"),
            StepAction(id="b", description="second", expected_output="o2"),
        ],
        execution_mode="parallel",
        reasoning="r",
    )
    state = LoopState(goal="g", thread_id="t-main")
    out = [x async for x in executor.execute(decision, state) if isinstance(x, StepResult)]

    assert len(out) == 2
    assert mock_agent.astream.call_count == 2


@pytest.mark.asyncio
async def test_plan_with_dependencies_drains_ready_chain() -> None:
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
        execution_mode="parallel",
        reasoning="r",
    )
    state = LoopState(goal="g", thread_id="t-main")

    out = [x async for x in executor.execute(decision, state) if isinstance(x, StepResult)]

    assert [r.step_id for r in out] == ["01", "02", "03"]
    assert mock_agent.astream.call_count == 3


def test_ledger_execute_ai_content_single_step_fills_from_chunks_ig373() -> None:
    """Trailing empty AIMessage after chunks must not produce empty ledger body (IG-373)."""
    mock_agent = MagicMock()
    executor = Executor(mock_agent, max_parallel_steps=4)
    messages: list = [
        AIMessageChunk(content="Here are the first lines:\n"),
        AIMessageChunk(content="A\nB\n"),
        AIMessage(content=""),
    ]
    body = executor._ledger_execute_ai_content(
        messages=messages,
        final_ai_msg=messages[-1],
        total_steps=1,
    )
    assert "Here are the first lines" in body
    assert "A\nB" in body


@pytest.mark.asyncio
async def test_parallel_waves_emit_step_wave_queued_for_overflow() -> None:
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
    queued: list[StepWaveQueued] = []
    async for item in executor.execute(decision, state):
        if isinstance(item, StepWaveQueued):
            queued.append(item)

    assert len(queued) == 1
    assert [s.id for s in queued[0].steps] == ["b"]


@pytest.mark.asyncio
async def test_parallel_waves_emit_step_wave_start_per_batch() -> None:
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
    wave_starts: list[StepWaveStart] = []
    async for item in executor.execute(decision, state):
        if isinstance(item, StepWaveStart):
            wave_starts.append(item)

    assert [tuple(w.steps) for w in wave_starts] == [
        (decision.steps[0],),
        (decision.steps[1],),
    ]


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
