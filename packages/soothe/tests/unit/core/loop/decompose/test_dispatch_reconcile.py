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
from soothe.sloop.stations.decompose.dispatch import DispatchNode
from soothe.sloop.stations.decompose.reconcile_node import ReconcileNode
from soothe.sloop.stations.decompose.root_eval import RootEvalNode


def _ctx_with_ce(ce: ContextEngine, goal_id: str, *, goal: str = "do work") -> LoopRuntimeContext:
    loop_state = SimpleNamespace(
        goal=goal,
        goal_user_submission=goal,
        iteration=0,
        max_iterations=8,
        current_decision=None,
        plan_id=None,
        step_results=[],
    )
    strange_loop = SimpleNamespace(
        config=SimpleNamespace(
            agent=SimpleNamespace(loop=SimpleNamespace(decompose=DecomposeLoopConfig()))
        )
    )
    checkpoint = SimpleNamespace(
        thread_health_metrics=SimpleNamespace(consecutive_rate_limit_errors=0),
    )
    return LoopRuntimeContext(
        strange_loop=strange_loop,  # type: ignore[arg-type]
        state_manager=MagicMock(),
        anchor_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=checkpoint,  # type: ignore[arg-type]
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
async def test_dispatch_plan_decision_carries_intake_label() -> None:
    from soothe_sdk.intention.models import TaskComplexity

    from soothe.sloop.intention.models import IntakeLabel, IntentClassification

    ce = ContextEngine()
    goal = await ce.create_goal("review arch", loop_id="L1")
    ctx = _ctx_with_ce(ce, goal.id, goal="review arch")
    ctx.loop_state.intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        task_complexity=TaskComplexity.SIMPLE,
        reasoning="I will review.",
    )
    await DispatchNode()(ctx, {})
    plan_calls = [
        call for call in ctx.emit.await_args_list if call.args and call.args[0] == "plan_decision"
    ]
    assert plan_calls
    assert plan_calls[0].args[1]["intake_label"] == "simple"


@pytest.mark.asyncio
async def test_dispatch_grounds_root_with_approved_plan() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("migrate auth", loop_id="L1")
    ctx = _ctx_with_ce(ce, goal.id, goal="migrate auth")
    ctx.loop_state.approved_plan_path = "/ws/.soothe/plans/demo.md"
    ctx.loop_state.approved_plan_markdown = (
        "# Solution\n\nUse OAuth.\n\n## Changes\n\n- Add token store\n"
    )
    node = DispatchNode()
    result = await node(ctx, {})
    assert result["dispatch_route"] == "execute"
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    root_id = ctx.scratch.decision.steps[0].id
    full = refreshed.steps.nodes[root_id].full_description or ""
    assert "<!-- soothe:approved-plan -->" in full
    assert "APPROVED PLAN" in full
    assert "Use OAuth" in full
    assert "decompose_task" in full
    assert ctx.loop_state.approved_plan_markdown is None
    assert ctx.loop_state.approved_plan_path is None


@pytest.mark.asyncio
async def test_dispatch_clears_planner_implement_handoff() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("migrate auth", loop_id="L1")
    ctx = _ctx_with_ce(ce, goal.id, goal="migrate auth")
    ctx.scratch.planner_implement_handoff = True
    ctx.loop_state.approved_plan_markdown = "# Solution\n\nUse OAuth.\n"
    node = DispatchNode()
    result = await node(ctx, {})
    assert result["dispatch_route"] == "execute"
    assert result.get("planner_implement_handoff") is False
    assert ctx.scratch.planner_implement_handoff is False
    assert ctx.loop_state.approved_plan_markdown is None


@pytest.mark.asyncio
async def test_dispatch_does_not_re_ground_already_stamped_root() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("migrate auth", loop_id="L1")
    stamped = "migrate auth\n\n<!-- soothe:approved-plan -->\n## APPROVED PLAN\n\nold body\n"
    await ce.add_step(
        goal.id,
        StepNode(
            id="ROOT",
            description="migrate auth",
            full_description=stamped,
            status="pending",
        ),
    )
    ctx = _ctx_with_ce(ce, goal.id, goal="migrate auth")
    ctx.loop_state.approved_plan_markdown = "# Solution\n\nNew body that must not replace\n"
    ctx.loop_state.approved_plan_path = "/ws/.soothe/plans/new.md"
    node = DispatchNode()
    await node(ctx, {})
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    assert refreshed.steps.nodes["ROOT"].full_description == stamped
    assert ctx.loop_state.approved_plan_markdown is None


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


@pytest.mark.asyncio
async def test_root_eval_inserts_eval_step_after_decomposition() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("do work", loop_id="L1")
    await ce.add_steps(
        goal.id,
        [
            StepNode(id="ROOT", description="root", status="decomposed"),
            StepNode(
                id="CHILD",
                description="child",
                status="completed",
                parent_step_id="ROOT",
            ),
        ],
    )
    ctx = _ctx_with_ce(ce, goal.id)
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "dispatch"
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    eval_nodes = [step for step in refreshed.steps.nodes.values() if step.kind == "eval"]
    assert len(eval_nodes) == 1
    assert eval_nodes[0].status == "pending"
    assert "ORIGINAL USER GOAL" in (eval_nodes[0].full_description or "")


@pytest.mark.asyncio
async def test_root_eval_finalizes_after_completed_eval() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("do work", loop_id="L1")
    await ce.add_steps(
        goal.id,
        [
            StepNode(id="ROOT", description="root", status="decomposed"),
            StepNode(
                id="CHILD",
                description="child",
                status="completed",
                parent_step_id="ROOT",
            ),
            StepNode(
                id="EVAL",
                description="eval",
                status="completed",
                kind="eval",
                plan_iteration=1,
            ),
        ],
    )
    ctx = _ctx_with_ce(ce, goal.id)
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "finalize"
