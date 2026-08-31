"""Tests for ROOT_EVAL read-only step retry (plan/ask interaction modes)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.config.models import DecomposeLoopConfig, EvalLoopConfig
from soothe.context.engine import ContextEngine
from soothe.context.models import StepNode
from soothe.sloop.orchestrator.runtime_context import LoopPhaseScratch, LoopRuntimeContext
from soothe.sloop.stations.decompose.root_eval import RootEvalNode


def _ctx_with_ce(
    ce: ContextEngine,
    goal_id: str,
    *,
    goal: str = "do work",
    interaction_mode: str | None = "plan",
    max_step_retries: int = 2,
) -> LoopRuntimeContext:
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
                    max_step_retries=max_step_retries,
                )
            )
        )
    )
    checkpoint = SimpleNamespace(
        thread_health_metrics=SimpleNamespace(consecutive_rate_limit_errors=0),
    )
    ctx = LoopRuntimeContext(
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
    ctx.interaction_mode = interaction_mode  # type: ignore[method-assign]
    return ctx


@pytest.mark.asyncio
async def test_plan_mode_failed_step_retries_to_dispatch() -> None:
    """A failed step in plan mode should be reset and routed to dispatch."""
    ce = ContextEngine()
    goal = await ce.create_goal("create file", loop_id="L1")
    await ce.add_step(
        goal.id,
        StepNode(id="ROOT", description="create file", status="failed"),
    )
    ctx = _ctx_with_ce(ce, goal.id, interaction_mode="plan")
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "dispatch"
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    root = refreshed.steps.nodes["ROOT"]
    assert root.status == "pending"
    assert root.retry_count == 1


@pytest.mark.asyncio
async def test_plan_mode_exhausted_retries_fall_through_to_finalize() -> None:
    """When retry_count >= max_step_retries, fall through to finalize."""
    ce = ContextEngine()
    goal = await ce.create_goal("create file", loop_id="L1")
    await ce.add_step(
        goal.id,
        StepNode(id="ROOT", description="create file", status="failed", retry_count=2),
    )
    ctx = _ctx_with_ce(ce, goal.id, interaction_mode="plan", max_step_retries=2)
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "finalize"


@pytest.mark.asyncio
async def test_plan_mode_no_failed_steps_finalizes() -> None:
    """Completed steps in plan mode should finalize, not retry."""
    ce = ContextEngine()
    goal = await ce.create_goal("do work", loop_id="L1")
    await ce.add_step(
        goal.id,
        StepNode(id="ROOT", description="root", status="completed"),
    )
    ctx = _ctx_with_ce(ce, goal.id, interaction_mode="plan")
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "finalize"


@pytest.mark.asyncio
async def test_ask_mode_failed_step_retries_to_dispatch() -> None:
    """Ask mode (read-only) should also retry failed steps."""
    ce = ContextEngine()
    goal = await ce.create_goal("ask question", loop_id="L1")
    await ce.add_step(
        goal.id,
        StepNode(id="ROOT", description="answer", status="failed"),
    )
    ctx = _ctx_with_ce(ce, goal.id, interaction_mode="ask")
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "dispatch"


@pytest.mark.asyncio
async def test_retries_disabled_falls_through_immediately() -> None:
    """When max_step_retries=0, retries are disabled and failed steps finalize."""
    ce = ContextEngine()
    goal = await ce.create_goal("create file", loop_id="L1")
    await ce.add_step(
        goal.id,
        StepNode(id="ROOT", description="create file", status="failed"),
    )
    ctx = _ctx_with_ce(ce, goal.id, interaction_mode="plan", max_step_retries=0)
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "finalize"


@pytest.mark.asyncio
async def test_non_readonly_mode_uses_normal_eval_path() -> None:
    """In non-read-only mode, failed steps follow the normal fatal path, not retry."""
    ce = ContextEngine()
    goal = await ce.create_goal("do work", loop_id="L1")
    await ce.add_step(
        goal.id,
        StepNode(id="ROOT", description="root", status="failed"),
    )
    ctx = _ctx_with_ce(ce, goal.id, interaction_mode=None)
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "fatal"


@pytest.mark.asyncio
async def test_partial_retry_only_resets_eligible_steps() -> None:
    """When some failed steps have exhausted retries and others haven't,
    only the eligible ones are reset; dispatch if any were reset."""
    ce = ContextEngine()
    goal = await ce.create_goal("multi step", loop_id="L1")
    await ce.add_steps(
        goal.id,
        [
            StepNode(id="A", description="step a", status="failed", retry_count=2),
            StepNode(id="B", description="step b", status="failed", retry_count=0),
        ],
    )
    ctx = _ctx_with_ce(ce, goal.id, interaction_mode="plan", max_step_retries=2)
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "dispatch"
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    assert refreshed.steps.nodes["A"].status == "failed"
    assert refreshed.steps.nodes["A"].retry_count == 2
    assert refreshed.steps.nodes["B"].status == "pending"
    assert refreshed.steps.nodes["B"].retry_count == 1


@pytest.mark.asyncio
async def test_retry_count_increments_across_retries() -> None:
    """Each retry attempt increments retry_count, and after max it stops."""
    ce = ContextEngine()
    goal = await ce.create_goal("create file", loop_id="L1")
    await ce.add_step(
        goal.id,
        StepNode(id="ROOT", description="create file", status="failed", retry_count=0),
    )
    ctx = _ctx_with_ce(ce, goal.id, interaction_mode="plan", max_step_retries=2)

    # First retry: retry_count 0 → 1, dispatch
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "dispatch"
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    assert refreshed.steps.nodes["ROOT"].retry_count == 1

    # Simulate the step failing again; second retry: retry_count 1 → 2, dispatch
    refreshed.steps.nodes["ROOT"].status = "failed"
    ce.defer_save()
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "dispatch"
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    assert refreshed.steps.nodes["ROOT"].retry_count == 2

    # Simulate the step failing a third time; now retry_count == max, finalize
    refreshed.steps.nodes["ROOT"].status = "failed"
    ce.defer_save()
    result = await RootEvalNode()(ctx, {})
    assert result["root_eval_route"] == "finalize"
