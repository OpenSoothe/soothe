"""Tests for non-blocking goal-completion tail persistence."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.foundation.context.planning import StepPlanManagerAdapter
from soothe.foundation.context.planning.models import CompletionStrategy
from soothe.foundation.sloop.engine.synthesis import SynthesisGenerator
from soothe.foundation.sloop.orchestrator.nodes.goal_completion import node_goal_completion
from soothe.foundation.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.foundation.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.foundation.sloop.state.schemas import LoopState, PlanResult
from soothe.foundation.sloop.utils.messages import LoopAIMessage


def _ctx(
    *,
    loop_state: LoopState,
    plan_manager: StepPlanManagerAdapter,
    strange_loop: Mock,
    state_manager: Mock,
    plan_result: PlanResult,
    ce: ContextEngine,
    goal: GoalNode,
) -> LoopRuntimeContext:
    scratch = LoopPhaseScratch(plan_result=plan_result, iteration_perf_start=None)
    return LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=state_manager,
        anchor_manager=Mock(),
        goal_context_manager=Mock(),
        plan_manager=plan_manager,
        checkpoint=Mock(),
        goal_record=Mock(goal_id="g1"),
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=AsyncMock(),
        scratch=scratch,
        ce=ce,
        ce_goal_id=goal.id,
    )


@pytest.mark.asyncio
async def test_completed_emits_before_finalize_goal_persistence() -> None:
    """``completed`` wire event must not wait on checkpoint finalize."""
    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )
    loop_state = LoopState(goal="do thing", thread_id="thr-1")
    goal = GoalNode(description="do thing")
    ce._dag.add_goal(goal)
    loop_state.bind_ce(ce, goal.id)
    plan_result = PlanResult(status="done", goal_progress="complete", require_goal_completion=False)
    pm = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.LEDGER_DIRECT)

    strange_loop = Mock()
    strange_loop.loop_planner = Mock()
    strange_loop.core_agent = Mock()
    strange_loop.config.agent.loop.final_response = "adaptive"
    strange_loop._fast_llm = None

    finalize_started = asyncio.Event()
    finalize_release = asyncio.Event()

    async def _slow_finalize(*_args: object, **_kwargs: object) -> None:
        finalize_started.set()
        await finalize_release.wait()

    sm = Mock()
    sm.loop_id = "test-loop-id"
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock(side_effect=_slow_finalize)

    loop_state.loop_messages.append(
        type("Msg", (), {"content": "done already", "phase": "execute_step"})()
    )

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        strange_loop=strange_loop,
        state_manager=sm,
        plan_result=plan_result,
        ce=ce,
        goal=goal,
    )

    with patch.object(
        SynthesisGenerator,
        "generate_synthesis",
        AsyncMock(),
    ):
        await node_goal_completion(ctx, {})

    completed_idx = next(
        i for i, c in enumerate(ctx.emit.await_args_list) if c.args and c.args[0] == "completed"
    )
    assert completed_idx >= 0
    assert ctx.tail_persistence_task is not None
    assert not ctx.tail_persistence_task.done()
    assert not finalize_started.is_set()

    await asyncio.wait_for(finalize_started.wait(), timeout=1.0)
    finalize_release.set()
    await ctx.tail_persistence_task
    sm.finalize_goal.assert_awaited()


@pytest.mark.asyncio
async def test_terminal_bootstrap_skips_duplicate_record_iteration() -> None:
    """record_iteration → goal_completion must not checkpoint twice (RFC-226)."""
    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )
    loop_state = LoopState(goal="continue task", thread_id="thr-1", iteration=1)
    goal = GoalNode(description="continue task")
    ce._dag.add_goal(goal)
    loop_state.bind_ce(ce, goal.id)

    plan_result = PlanResult(
        status="done",
        goal_progress="complete",
        require_goal_completion=True,
        terminal_after_execute=True,
    )
    pm = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
    pm.determine_completion_strategy = Mock(return_value=CompletionStrategy.LEDGER_DIRECT)

    strange_loop = Mock()
    strange_loop.config.agent.loop.final_response = "adaptive"
    strange_loop._fast_llm = None

    sm = Mock()
    sm.loop_id = "loop-terminal-bootstrap"
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    loop_state.loop_messages.append(
        LoopAIMessage(content="bootstrap answer", thread_id="thr-1", phase="execute")
    )

    ctx = _ctx(
        loop_state=loop_state,
        plan_manager=pm,
        strange_loop=strange_loop,
        state_manager=sm,
        plan_result=plan_result,
        ce=ce,
        goal=goal,
    )

    await node_goal_completion(ctx, {"after_record_route": "goal_completion"})

    sm.record_iteration.assert_not_called()
    assert loop_state.iteration == 1
