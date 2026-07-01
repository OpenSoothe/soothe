"""Execute node step lifecycle events for live TUI (step_started / step_completed)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from soothe.foundation.sloop.engine.executor import StepWaveQueued, StepWaveStart
from soothe.foundation.sloop.orchestrator.nodes.execute_steps import node_execute
from soothe.foundation.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.foundation.sloop.state.schemas import AgentDecision, StepAction, StepResult


async def _fake_execute_stream(*_args: Any, **_kwargs: Any):
    yield StepWaveQueued(steps=(StepAction(id="WAA-02", description="Second"),))
    yield StepWaveStart(steps=(StepAction(id="WAA-01", description="First"),))
    yield ("ns", "messages", ("chunk", {}))
    yield StepResult(
        step_id="WAA-01",
        success=True,
        duration_ms=100,
        thread_id="thread-1",
        tool_call_count=2,
    )
    yield StepResult(
        step_id="WAA-02",
        success=True,
        duration_ms=200,
        thread_id="thread-1",
        tool_call_count=0,
    )


@pytest.mark.asyncio
async def test_execute_emits_step_completed_per_result() -> None:
    """TUI must see completion when each parallel step finishes, not after the full wave."""
    emitted: list[tuple[str, Any]] = []

    async def emit(event_type: str, event_data: Any) -> None:
        emitted.append((event_type, event_data))

    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="WAA-01", description="First"),
            StepAction(id="WAA-02", description="Second"),
        ],
        execution_mode="parallel",
    )
    loop_state = MagicMock()
    loop_state.dependency_completion_ids.return_value = set()
    loop_state.workspace = None
    loop_state.thread_id = "thread-1"
    loop_state.working_memory = None
    loop_state.add_step_result = MagicMock()

    scratch = MagicMock()
    scratch.decision = decision
    scratch.plan_result = MagicMock()

    strange_loop = MagicMock()
    strange_loop.config.agent.loop.concurrency.max_parallel_steps = 4

    ctx = LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(loop_id="loop-1"),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=MagicMock(),
        goal_record=None,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=emit,
        scratch=scratch,
    )

    import soothe.foundation.sloop.orchestrator.nodes.execute_steps as mod

    mock_executor = MagicMock()
    mock_executor.execute = _fake_execute_stream
    mod.Executor = MagicMock(return_value=mock_executor)

    await node_execute(ctx, {})

    queued = [e for e in emitted if e[0] == "step_queued"]
    assert [q[1]["step_id"] for q in queued] == ["WAA-02"]

    started = [e for e in emitted if e[0] == "step_started"]
    assert [s[1]["step_id"] for s in started] == ["WAA-01"]

    completed = [e for e in emitted if e[0] == "step_completed"]
    assert len(completed) == 2
    assert completed[0][1]["step_id"] == "WAA-01"
    assert completed[0][1]["tool_call_count"] == 2
    assert completed[1][1]["step_id"] == "WAA-02"
    assert loop_state.add_step_result.call_count == 2


async def _fake_dependency_execute_stream(*_args: Any, **_kwargs: Any):
    """Simulate dependency DAG: one step at a time, second starts after first completes."""
    yield StepWaveStart(steps=(StepAction(id="WAA-01", description="First"),))
    yield StepResult(
        step_id="WAA-01",
        success=True,
        duration_ms=100,
        thread_id="thread-1",
        tool_call_count=2,
    )
    yield StepWaveStart(steps=(StepAction(id="WAA-02", description="Second"),))
    yield StepResult(
        step_id="WAA-02",
        success=True,
        duration_ms=200,
        thread_id="thread-1",
        tool_call_count=0,
    )


@pytest.mark.asyncio
async def test_execute_emits_step_started_when_dependency_unlocks() -> None:
    """Dependency DAG must emit step_started for step 2 when step 1 completes (TUI pending cards)."""
    emitted: list[tuple[str, Any]] = []

    async def emit(event_type: str, event_data: Any) -> None:
        emitted.append((event_type, event_data))

    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="WAA-01", description="First"),
            StepAction(id="WAA-02", description="Second", dependencies=["WAA-01"]),
        ],
        execution_mode="parallel",
    )
    loop_state = MagicMock()
    loop_state.dependency_completion_ids.return_value = set()
    loop_state.workspace = None
    loop_state.thread_id = "thread-1"
    loop_state.working_memory = None
    loop_state.add_step_result = MagicMock()

    scratch = MagicMock()
    scratch.decision = decision
    scratch.plan_result = MagicMock()

    strange_loop = MagicMock()
    strange_loop.config.agent.loop.concurrency.max_parallel_steps = 4

    ctx = LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(loop_id="loop-1"),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=MagicMock(),
        goal_record=None,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=emit,
        scratch=scratch,
    )

    import soothe.foundation.sloop.orchestrator.nodes.execute_steps as mod

    mock_executor = MagicMock()
    mock_executor.execute = _fake_dependency_execute_stream
    mod.Executor = MagicMock(return_value=mock_executor)

    await node_execute(ctx, {})

    started = [e for e in emitted if e[0] == "step_started"]
    assert [s[1]["step_id"] for s in started] == ["WAA-01", "WAA-02"]
    # step 2 must not be announced until after step 1 completes
    completed_idx = next(i for i, e in enumerate(emitted) if e[0] == "step_completed")
    started_waa02_idx = next(
        i for i, e in enumerate(emitted) if e[0] == "step_started" and e[1]["step_id"] == "WAA-02"
    )
    assert started_waa02_idx > completed_idx
