"""IG-555 plan_generate undersized-plan replan guardrail."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.sloop.cognition.plan_step_safety import MAX_UNDERSIZED_PLAN_REPLANS
from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.nodes.plan_generate import node_plan_generate
from soothe.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.sloop.orchestrator.routing import route_after_plan
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.orchestrator.state import PLAN_ROUTE_EXECUTE
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
    StatusAssessment,
    StepAction,
)


def _one_step_plan() -> PlanResult:
    return PlanResult(
        status="continue",
        plan_action="new",
        decision=AgentDecision(
            type="execute_steps",
            steps=[StepAction(id="01", description="Apply prior recommendation")],
            execution_mode="parallel",
        ),
        next_action="Apply recommendation",
        goal_progress="none",
    )


def _two_step_plan() -> PlanResult:
    return PlanResult(
        status="continue",
        plan_action="new",
        decision=AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(id="01", description="Build image"),
                StepAction(id="02", description="Run e2e"),
            ],
            execution_mode="dependency",
        ),
        next_action="Build then test",
        goal_progress="none",
    )


def _make_ctx(*, replan_attempts: int = 0) -> LoopRuntimeContext:
    loop_state = LoopState(goal="build then test", thread_id="tid", iteration=0)
    loop_state.intent = SimpleNamespace(intake_label=IntakeLabel.COMPLEX)

    strange_loop = MagicMock()
    strange_loop._build_plan_context.return_value = MagicMock()
    strange_loop.plan_phase.generate_from_assessment = AsyncMock(return_value=_one_step_plan())

    return LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=None,
        goal_record=None,
        continue_loop_mode=True,
        recovery_valid_resume=False,
        loop_state=loop_state,
        emit=AsyncMock(),
        scratch=LoopPhaseScratch(
            plan_assessment=StatusAssessment(status="continue", goal_progress="low"),
            undersized_plan_replan_attempts=replan_attempts,
        ),
        ce=None,
        ce_goal_id=None,
    )


@pytest.mark.asyncio
async def test_undersized_plan_returns_continue_generate_route() -> None:
    ctx = _make_ctx()
    result = await node_plan_generate(ctx, {})
    assert result.get("assess_route") == "continue_generate"
    assert ctx.scratch.plan_result is None
    assert ctx.scratch.undersized_plan_replan_attempts == 1
    assert route_after_plan(result) == "plan_generate"


@pytest.mark.asyncio
async def test_valid_plan_clears_assess_route_and_routes_to_execute() -> None:
    ctx = _make_ctx()
    ctx.strange_loop.plan_phase.generate_from_assessment = AsyncMock(return_value=_two_step_plan())

    result = await node_plan_generate(ctx, {})
    assert result.get("plan_route") == PLAN_ROUTE_EXECUTE
    assert result.get("assess_route") is None
    assert ctx.scratch.plan_result is not None
    assert ctx.scratch.undersized_plan_replan_attempts == 0
    assert route_after_plan(result) == "resolve_decision"


@pytest.mark.asyncio
async def test_persistent_undersized_plan_fatals_after_max_replans() -> None:
    ctx = _make_ctx(replan_attempts=MAX_UNDERSIZED_PLAN_REPLANS)
    result = await node_plan_generate(ctx, {})
    assert result.get("last_outcome") == "fatal"
    assert result.get("assess_route") is None
    assert route_after_plan(result) == "resolve_decision"
    ctx.emit.assert_awaited()
