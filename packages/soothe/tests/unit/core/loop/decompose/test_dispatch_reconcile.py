"""Unit tests for DISPATCH / RECONCILE / ROOT_EVAL stations (IG-751 P3)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.config.models import DecomposeLoopConfig, EvalLoopConfig
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
            agent=SimpleNamespace(
                loop=SimpleNamespace(
                    decompose=DecomposeLoopConfig(),
                    eval=EvalLoopConfig(),
                )
            )
        )
    )
    checkpoint = SimpleNamespace(
        thread_health_metrics=SimpleNamespace(consecutive_rate_limit_errors=0),
    )
    return LoopRuntimeContext(
        strange_loop=strange_loop,  # type: ignore[arg-type]
        state_manager=MagicMock(),
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
async def test_dispatch_grounds_approved_plan() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("migrate auth", loop_id="L1")
    ctx = _ctx_with_ce(ce, goal.id, goal="migrate auth")
    ctx.loop_state.approved_plan_markdown = "# Solution\n\nUse OAuth.\n"
    node = DispatchNode()
    result = await node(ctx, {})
    assert result["dispatch_route"] == "execute"
    # Approved plan is consumed (cleared) by the grounding path.
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


@pytest.mark.asyncio
async def test_root_eval_minimal_skips_eval_and_finalizes() -> None:
    """Trivial tasks skip the coverage Eval phase and go directly to finalize,
    even with a decomposed action tree that would otherwise require Eval."""
    from soothe_sdk.intention.models import TaskComplexity

    from soothe.sloop.intention.models import IntakeLabel, IntentClassification

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
    ctx.loop_state.intent = IntentClassification(
        intake_label=IntakeLabel.MINIMAL,
        task_complexity=TaskComplexity.MINIMAL,
    )
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "finalize"


@pytest.mark.asyncio
async def test_root_eval_simple_llm_decides_skip(monkeypatch) -> None:
    """SIMPLE tasks: when the LLM decides no coverage audit is needed, skip
    Eval and finalize. This replaces the old deterministic SIMPLE skip."""
    from soothe_sdk.intention.models import TaskComplexity

    from soothe.sloop.eval.eval_decision import EvalDecision
    from soothe.sloop.intention.models import IntakeLabel, IntentClassification

    async def _fake_decide(*args, **kwargs):
        return EvalDecision(should_run_eval=False, reasoning="Goal fully achieved.")

    # The lazy import inside RootEvalNode.process resolves the function at call
    # time from the eval_decision module, so patch the source module.
    monkeypatch.setattr(
        "soothe.sloop.eval.eval_decision.decide_eval_required",
        _fake_decide,
    )

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
    ctx.strange_loop._fast_llm = None  # LLM call is mocked; fast_model not used
    ctx.loop_state.intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        task_complexity=TaskComplexity.SIMPLE,
    )
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "finalize"


@pytest.mark.asyncio
async def test_root_eval_simple_llm_decides_run_eval(monkeypatch) -> None:
    """SIMPLE tasks: when the LLM decides a coverage audit IS needed, insert
    an Eval step and route to dispatch."""
    from soothe_sdk.intention.models import TaskComplexity

    from soothe.sloop.eval.eval_decision import EvalDecision
    from soothe.sloop.intention.models import IntakeLabel, IntentClassification

    async def _fake_decide(*args, **kwargs):
        return EvalDecision(should_run_eval=True, reasoning="Worker early-terminated.")

    monkeypatch.setattr(
        "soothe.sloop.eval.eval_decision.decide_eval_required",
        _fake_decide,
    )

    ce = ContextEngine()
    goal = await ce.create_goal("do work", loop_id="L1")
    await ce.add_steps(
        goal.id,
        [
            StepNode(id="ROOT", description="root", status="completed"),
        ],
    )
    ctx = _ctx_with_ce(ce, goal.id)
    ctx.strange_loop._fast_llm = None
    ctx.loop_state.intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        task_complexity=TaskComplexity.SIMPLE,
    )
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "dispatch"
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    eval_nodes = [step for step in refreshed.steps.nodes.values() if step.kind == "eval"]
    assert len(eval_nodes) == 1
    assert eval_nodes[0].status == "pending"


@pytest.mark.asyncio
async def test_root_eval_simple_no_fast_model_fails_safe() -> None:
    """SIMPLE tasks: when no fast model is available, fail-safe to running
    Eval (should_run_eval=True) rather than silently skipping."""
    from soothe_sdk.intention.models import TaskComplexity

    from soothe.sloop.intention.models import IntakeLabel, IntentClassification

    ce = ContextEngine()
    goal = await ce.create_goal("do work", loop_id="L1")
    await ce.add_steps(
        goal.id,
        [
            StepNode(id="ROOT", description="root", status="completed"),
        ],
    )
    ctx = _ctx_with_ce(ce, goal.id)
    ctx.strange_loop._fast_llm = None
    ctx.loop_state.intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        task_complexity=TaskComplexity.SIMPLE,
    )
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "dispatch"
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    eval_nodes = [step for step in refreshed.steps.nodes.values() if step.kind == "eval"]
    assert len(eval_nodes) == 1


@pytest.mark.asyncio
async def test_root_eval_complex_inserts_eval_step() -> None:
    """Complex tasks still run the full coverage Eval gate when Eval is
    required — the simple/minimal skip does not apply."""
    from soothe_sdk.intention.models import TaskComplexity

    from soothe.sloop.intention.models import IntakeLabel, IntentClassification

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
    ctx.loop_state.intent = IntentClassification(
        intake_label=IntakeLabel.COMPLEX,
        task_complexity=TaskComplexity.COMPLEX,
    )
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "dispatch"
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    eval_nodes = [step for step in refreshed.steps.nodes.values() if step.kind == "eval"]
    assert len(eval_nodes) == 1
    assert eval_nodes[0].status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["plan", "ask"])
async def test_root_eval_readonly_mode_skips_eval(mode: str) -> None:
    """Plan/ask interaction modes never run the coverage Eval — no Eval
    StepNode insertion and no eval-decision LLM call, even when the action
    tree would otherwise require one."""
    from soothe_sdk.intention.models import TaskComplexity

    from soothe.sloop.intention.models import IntakeLabel, IntentClassification

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
    ctx.interaction_mode = mode
    ctx.loop_state.intent = IntentClassification(
        intake_label=IntakeLabel.COMPLEX,
        task_complexity=TaskComplexity.COMPLEX,
    )
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "finalize"
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    eval_nodes = [step for step in refreshed.steps.nodes.values() if step.kind == "eval"]
    assert not eval_nodes


@pytest.mark.asyncio
async def test_dispatch_claims_pending_eval_after_max_waves() -> None:
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
                status="pending",
                kind="eval",
                parent_step_id="ROOT",
                plan_iteration=1,
            ),
        ],
    )
    ctx = _ctx_with_ce(ce, goal.id)
    ctx.loop_state.iteration = 1
    ctx.strange_loop.config.agent.loop.decompose = DecomposeLoopConfig(max_waves=1)
    result = await DispatchNode()(ctx, {})
    assert result["dispatch_route"] == "execute"
    assert ctx.scratch.decision is not None
    assert [step.id for step in ctx.scratch.decision.steps] == ["EVAL"]
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    assert refreshed.steps.nodes["EVAL"].status == "active"
