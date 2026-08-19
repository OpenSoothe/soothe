"""Unit tests for DISPATCH / RECONCILE / ROOT_EVAL stations (IG-751 P3)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.config.models import DecomposeLoopConfig
from soothe.context.decomposition import DecompositionProposal, ProposedSubtask
from soothe.context.engine import ContextEngine
from soothe.context.models import StepNode
from soothe.sloop.orchestrator.runtime_context import LoopPhaseScratch, LoopRuntimeContext
from soothe.sloop.stages.decompose.dispatch import DispatchNode
from soothe.sloop.stages.decompose.reconcile_node import ReconcileNode
from soothe.sloop.stages.decompose.root_eval import RootEvalNode


def _ctx_with_ce(ce: ContextEngine, goal_id: str, *, goal: str = "do work") -> LoopRuntimeContext:
    loop_state = SimpleNamespace(
        goal=goal,
        goal_user_submission=goal,
        iteration=0,
        current_decision=None,
        plan_id=None,
        step_results=[],
    )
    strange_loop = SimpleNamespace(
        config=SimpleNamespace(
            agent=SimpleNamespace(loop=SimpleNamespace(decompose=DecomposeLoopConfig()))
        )
    )
    return LoopRuntimeContext(
        strange_loop=strange_loop,  # type: ignore[arg-type]
        state_manager=MagicMock(),
        anchor_manager=MagicMock(),
        goal_context_manager=None,
        plan_manager=MagicMock(),
        checkpoint=MagicMock(),
        goal_record=None,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=loop_state,  # type: ignore[arg-type]
        emit=AsyncMock(),
        ce=ce,
        ce_goal_id=goal_id,
        scratch=LoopPhaseScratch(),
    )


@pytest.mark.asyncio
async def test_dispatch_creates_root_and_claims() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("do work", loop_id="L1")
    ctx = _ctx_with_ce(ce, goal.id)
    node = DispatchNode()
    result = await node(ctx, {})
    assert result["dispatch_route"] == "execute"
    assert ctx.scratch.decision is not None
    assert len(ctx.scratch.decision.steps) == 1
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    root_id = ctx.scratch.decision.steps[0].id
    assert refreshed.steps.nodes[root_id].status == "active"


@pytest.mark.asyncio
async def test_reconcile_commits_and_routes_dispatch() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("do work", loop_id="L1")
    await ce.add_step(goal.id, StepNode(id="ROOT", description="root", status="active"))
    ctx = _ctx_with_ce(ce, goal.id)
    ctx.scratch.decompose_proposals = [
        DecompositionProposal(
            parent_step_id="ROOT",
            subtasks=[ProposedSubtask(description="child")],
        )
    ]
    node = ReconcileNode()
    result = await node(ctx, {})
    assert result["reconcile_route"] == "dispatch"
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    assert refreshed.steps.nodes["ROOT"].status == "decomposed"
    assert len(refreshed.steps.ready_steps()) == 1


@pytest.mark.asyncio
async def test_root_eval_finalize_when_tree_green() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("do work", loop_id="L1")
    await ce.add_step(
        goal.id,
        StepNode(id="ROOT", description="root", status="completed"),
    )
    ctx = _ctx_with_ce(ce, goal.id)
    node = RootEvalNode()
    result = await node(ctx, {})
    assert result["root_eval_route"] == "finalize"
