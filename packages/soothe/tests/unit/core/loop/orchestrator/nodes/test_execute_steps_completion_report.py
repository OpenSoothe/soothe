"""Execute node forwards step completion cognition reports."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.foundation.sloop.engine.executor import StepWaveStart
from soothe.foundation.sloop.engine.step_wave_types import StepCompletionReport
from soothe.foundation.sloop.orchestrator.nodes.execute_steps import node_execute
from soothe.foundation.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.foundation.sloop.state.schemas import AgentDecision, StepAction, StepResult


async def _fake_execute_stream(*_args: Any, **_kwargs: Any):
    yield StepWaveStart(steps=(StepAction(id="WAA-01", description="First"),))
    yield StepCompletionReport(
        step_id="WAA-01",
        summary="I finished the first step.",
        iteration=2,
    )
    yield StepResult(
        step_id="WAA-01",
        success=True,
        duration_ms=100,
        thread_id="thread-1",
        tool_call_count=1,
    )


@pytest.mark.asyncio
async def test_execute_emits_step_completion_report_before_completed() -> None:
    emitted: list[tuple[str, Any]] = []

    async def emit(event_type: str, event_data: Any) -> None:
        emitted.append((event_type, event_data))

    decision = AgentDecision(
        type="execute_steps",
        steps=[StepAction(id="WAA-01", description="First")],
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

    report_events = [e for e in emitted if e[0] == "step_completion_report"]
    completed_events = [e for e in emitted if e[0] == "step_completed"]
    assert len(report_events) == 1
    assert report_events[0][1]["summary"] == "I finished the first step."
    assert report_events[0][1]["step_id"] == "WAA-01"
    assert len(completed_events) == 1
    assert emitted.index(report_events[0]) < emitted.index(completed_events[0])
