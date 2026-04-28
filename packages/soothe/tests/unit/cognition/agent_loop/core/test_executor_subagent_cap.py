"""Executor subagent task cap wiring (IG-130)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.cognition.agent_loop.core.executor import Executor
from soothe.cognition.agent_loop.state.schemas import LoopState, StepAction, StepResult
from soothe.config import SootheConfig


def _make_step() -> StepAction:
    return StepAction(
        id="s0",
        description="Call subagent once",
        tools=[],
        subagent=None,
        expected_output="ok",
        dependencies=[],
    )


@pytest.mark.asyncio
async def test_stream_stops_after_subagent_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.messages import ToolMessage

    cfg = SootheConfig()
    cfg.agentic.max_subagent_tasks_per_wave = 1

    agent = MagicMock()
    chunks: list = [
        ((), "messages", (ToolMessage(content="a", tool_call_id="1", name="task"), {})),
        ((), "messages", (ToolMessage(content="b", tool_call_id="2", name="task"), {})),
        ((), "messages", (ToolMessage(content="c", tool_call_id="3", name="grep"), {})),
    ]

    async def fake_astream(*_a: object, **_k: object):
        for c in chunks:
            yield c

    agent.astream = fake_astream

    ex = Executor(agent, max_parallel_steps=1, config=cfg)
    state = LoopState(goal="g", thread_id="t", max_iterations=3)
    step = _make_step()

    out = [item async for item in ex._execute_sequential_chunk([step], state)]

    results = [x for x in out if isinstance(x, StepResult)]
    assert len(results) == 1
    sr = results[0]
    assert sr.success
    assert sr.subagent_task_completions == 2
    assert sr.hit_subagent_cap is True


@pytest.mark.asyncio
async def test_unlimited_subagent_when_cap_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.messages import ToolMessage

    cfg = SootheConfig()
    cfg.agentic.max_subagent_tasks_per_wave = 0

    agent = MagicMock()
    chunks: list = [
        ((), "messages", (ToolMessage(content="a", tool_call_id="1", name="task"), {})),
        ((), "messages", (ToolMessage(content="b", tool_call_id="2", name="task"), {})),
    ]

    async def fake_astream(*_a: object, **_k: object):
        for c in chunks:
            yield c

    agent.astream = fake_astream

    ex = Executor(agent, max_parallel_steps=1, config=cfg)
    state = LoopState(goal="g", thread_id="t", max_iterations=3)
    step = _make_step()

    out = [item async for item in ex._execute_sequential_chunk([step], state)]

    results = [x for x in out if isinstance(x, StepResult)]
    sr = results[0]
    assert sr.hit_subagent_cap is False
    assert sr.subagent_task_completions == 2
