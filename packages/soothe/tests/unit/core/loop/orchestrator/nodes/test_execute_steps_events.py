"""Execute node emits step_completed as each StepResult arrives (not only after the wave)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.core.loop.orchestrator.nodes.execute_steps import node_execute
from soothe.core.loop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.core.loop.state.schemas import AgentDecision, StepAction, StepResult


async def _fake_execute_stream(*_args: Any, **_kwargs: Any):
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

    agent_loop = MagicMock()
    agent_loop.config.agent_loop.limits.max_parallel_steps = 4

    ctx = LoopRuntimeContext(
        agent_loop=agent_loop,
        state_manager=MagicMock(loop_id="loop-1"),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=MagicMock(),
        goal_record=None,
        continue_thread_mode=False,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=emit,
        scratch=scratch,
    )

    import soothe.core.loop.orchestrator.nodes.execute_steps as mod

    mock_executor = MagicMock()
    mock_executor.execute = _fake_execute_stream
    mod.Executor = MagicMock(return_value=mock_executor)

    await node_execute(ctx, {})

    completed = [e for e in emitted if e[0] == "step_completed"]
    assert len(completed) == 2
    assert completed[0][1]["step_id"] == "WAA-01"
    assert completed[0][1]["tool_call_count"] == 2
    assert completed[1][1]["step_id"] == "WAA-02"
    assert loop_state.add_step_result.call_count == 2
