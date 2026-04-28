"""Executor sequential waves: one StepResult per StepAction (scheme B), chunked by max_parallel_steps."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.cognition.agent_loop.core.executor import Executor
from soothe.cognition.agent_loop.state.schemas import (
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
