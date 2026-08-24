"""Plan reject terminates the goal without a completion report.

Rejecting a plan discards it, so ``node_goal_completion`` must skip synthesis,
the ``goal_completion`` ledger pair, and any user-facing output — the operator
asked for none.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.context.engine import ContextEngine
from soothe.context.models import GoalNode
from soothe.context.store_sqlite import SqliteContextPersistence
from soothe.sloop.engine.completion.synthesis import SynthesisGenerator
from soothe.sloop.orchestrator.runtime_context import LoopPhaseScratch, LoopRuntimeContext
from soothe.sloop.state.schemas import LoopState
from soothe.sloop.stations.completion.finalize import node_goal_completion


def _reject_ctx() -> tuple[LoopRuntimeContext, ContextEngine, GoalNode]:
    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )
    goal = GoalNode(description="count one to five", status="active")
    ce._dag.add_goal(goal)
    loop_state = LoopState(goal="count one to five", thread_id="thr-reject")
    loop_state.bind_ce(ce, goal.id)

    sm = Mock()
    sm.loop_id = "loop-reject"
    sm.record_iteration = AsyncMock()
    sm.finalize_goal = AsyncMock()

    ctx = LoopRuntimeContext(
        strange_loop=Mock(),
        state_manager=sm,
        anchor_manager=Mock(),
        plan_manager=Mock(),
        checkpoint=Mock(),
        goal_record=Mock(goal_id="g1"),
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=AsyncMock(),
        scratch=LoopPhaseScratch(plan_rejected=True, plan_result=None),
        ce=ce,
        ce_goal_id=goal.id,
    )
    return ctx, ce, goal


@pytest.mark.asyncio
async def test_reject_emits_completed_without_report() -> None:
    ctx, _ce, _goal = _reject_ctx()

    with patch.object(SynthesisGenerator, "generate_synthesis") as synthesis:
        out = await node_goal_completion(ctx, {})

    synthesis.assert_not_called()
    assert out == {"last_outcome": "completed"}

    payload = next(
        (c.args[1] for c in ctx.emit.await_args_list if c.args and c.args[0] == "completed"),
        None,
    )
    assert payload is not None
    assert payload["skip_goal_completion_wire_duplicate"] is True
    assert not (payload["result"].full_output or "")
    assert not (payload["result"].evidence_summary or "")
    assert payload["result"].next_action == "Plan rejected."


@pytest.mark.asyncio
async def test_reject_writes_no_goal_completion_ledger_pair() -> None:
    ctx, _ce, _goal = _reject_ctx()

    await node_goal_completion(ctx, {})

    assert ctx.loop_state.loop_messages == []


@pytest.mark.asyncio
async def test_reject_cancels_ce_goal_and_clears_scratch() -> None:
    ctx, ce, goal = _reject_ctx()

    await node_goal_completion(ctx, {})

    assert ce._dag.get_goal(goal.id).status == "cancelled"
    assert ctx.scratch.plan_rejected is False
    assert ctx.scratch.plan_result is None
