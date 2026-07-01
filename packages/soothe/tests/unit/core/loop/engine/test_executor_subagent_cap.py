"""Executor subagent task cap wiring (IG-130)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe.foundation.sloop.engine.executor import Executor
from soothe.foundation.sloop.state.schemas import AgentDecision, LoopState, StepAction, StepResult

from soothe.config import SootheConfig
from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence


def _make_ce() -> ContextEngine:
    """Create a ContextEngine with sqlite :memory: backend for tests."""
    return ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )


def _make_step() -> StepAction:
    return StepAction(
        id="s0",
        description="Call subagent once",
        subagent=None,
        expected_output="ok",
        dependencies=[],
    )


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
async def test_stream_stops_after_subagent_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.messages import ToolMessage

    cfg = SootheConfig()
    cfg.agent.loop.max_subagent_tasks_per_wave = 1

    chunks: list = [
        ((), "messages", (ToolMessage(content="a", tool_call_id="1", name="task"), {})),
        ((), "messages", (ToolMessage(content="b", tool_call_id="2", name="task"), {})),
        ((), "messages", (ToolMessage(content="c", tool_call_id="3", name="grep"), {})),
    ]
    agent = _make_mock_agent(chunks)

    ex = Executor(agent, max_parallel_steps=1, config=cfg, context_engine=_make_ce())
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
    assert sr.success
    assert sr.subagent_task_completions == 2
    assert sr.hit_subagent_cap is True


@pytest.mark.asyncio
async def test_unlimited_subagent_when_cap_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.messages import ToolMessage

    cfg = SootheConfig()
    cfg.agent.loop.max_subagent_tasks_per_wave = 0

    chunks: list = [
        ((), "messages", (ToolMessage(content="a", tool_call_id="1", name="task"), {})),
        ((), "messages", (ToolMessage(content="b", tool_call_id="2", name="task"), {})),
    ]
    agent = _make_mock_agent(chunks)

    ex = Executor(agent, max_parallel_steps=1, config=cfg, context_engine=_make_ce())
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
    sr = results[0]
    assert sr.hit_subagent_cap is False
    assert sr.subagent_task_completions == 2
