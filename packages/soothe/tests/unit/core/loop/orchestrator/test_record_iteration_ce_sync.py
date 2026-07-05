"""Tests for record_iteration CE iteration sync and tail persist surfacing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.foundation.sloop.state.schemas import AgentDecision, LoopState, PlanResult, StepAction


@pytest.mark.asyncio
async def test_record_iteration_increments_ce_iteration_count() -> None:
    from soothe.foundation.sloop.orchestrator.nodes.record_iteration import node_record_iteration
    from soothe.foundation.sloop.orchestrator.phase_scratch import LoopPhaseScratch
    from soothe.foundation.sloop.orchestrator.runtime_context import LoopRuntimeContext

    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )
    goal = GoalNode(description="goal")
    ce._dag.add_goal(goal)
    loop_state = LoopState(goal="goal", thread_id="t1")
    loop_state.bind_ce(ce, goal.id)

    plan_result = PlanResult(
        status="continue",
        goal_progress="low",
        decision=AgentDecision(
            type="execute_steps",
            steps=[StepAction(id="S1", description="step", dependencies=None)],
            execution_mode="parallel",
        ),
    )
    decision = plan_result.decision
    assert decision is not None
    ctx = LoopRuntimeContext(
        strange_loop=Mock(),
        state_manager=Mock(record_iteration=AsyncMock()),
        anchor_manager=Mock(capture_iteration_end_anchor=AsyncMock()),
        goal_context_manager=Mock(),
        plan_manager=Mock(record_step_outcomes=Mock()),
        checkpoint=Mock(),
        goal_record=Mock(goal_id="g1"),
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=AsyncMock(),
        scratch=LoopPhaseScratch(
            plan_result=plan_result,
            decision=decision,
            step_results=[],
            iteration_perf_start=None,
        ),
        ce=ce,
        ce_goal_id=goal.id,
    )

    await node_record_iteration(ctx, {})

    assert ce.get_iteration(goal.id) == 1


@pytest.mark.asyncio
async def test_tail_persistence_surfaces_ce_save_failure(caplog: pytest.LogCaptureFixture) -> None:
    from soothe.foundation.sloop.orchestrator.nodes.goal_completion import (
        _goal_completion_tail_persistence,
    )

    caplog.set_level("WARNING")
    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )
    ce.save = AsyncMock(side_effect=RuntimeError("disk full"))  # type: ignore[method-assign]
    sm = Mock(finalize_goal=AsyncMock())

    failures = await _goal_completion_tail_persistence(
        context_engine=ce,
        state_manager=sm,
        goal_record=Mock(),
        full_output="answer",
        loop_state=LoopState(goal="g", thread_id="t1"),
        loop_id="loop-abc",
    )

    assert failures == ["ce_save:RuntimeError"]
    assert any(
        "Goal-completion CE save failed for loop loop-abc" in r.message for r in caplog.records
    )
    sm.finalize_goal.assert_awaited_once()
