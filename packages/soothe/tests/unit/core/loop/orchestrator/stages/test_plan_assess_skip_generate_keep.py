"""Assess routes skip_generate when continue + remaining steps (IG-671)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.protocols.planner import PlanContext

from soothe.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.stages.plan.assess import node_plan_assess
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    StatusAssessment,
    StepAction,
    StepExecutionRecord,
)


def _make_ctx() -> LoopRuntimeContext:
    state = LoopState(
        goal="ship feature",
        thread_id="t1",
        iteration=1,
        current_decision=AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(id="01", description="First"),
                StepAction(id="02", description="Second"),
            ],
            execution_mode="parallel",
        ),
    )
    state.add_step_result(
        StepExecutionRecord(step_id="01", success=True, duration_ms=10, thread_id="t1")
    )

    strange_loop = MagicMock()
    strange_loop._build_plan_context.return_value = PlanContext()
    strange_loop.plan_phase.assess_status = AsyncMock(
        return_value=StatusAssessment(
            status="continue",
            goal_progress="medium",
            assessment_reasoning="",
            require_goal_completion=False,
        )
    )
    strange_loop.plan_phase.finalize_plan_result = MagicMock(side_effect=lambda **kw: kw["result"])
    strange_loop.config = None

    return LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(loop_id="loop-keep"),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=MagicMock(),
        goal_record=None,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=state,
        emit=AsyncMock(),
        scratch=LoopPhaseScratch(),
        ce=None,
        ce_goal_id=None,
    )


@pytest.mark.asyncio
async def test_assess_continue_with_remaining_skips_generate() -> None:
    ctx = _make_ctx()
    out = await node_plan_assess(ctx, {})
    assert out.get("assess_route") == "skip_generate"
    assert ctx.scratch.plan_result is not None
    assert ctx.scratch.plan_result.plan_action == "keep"
    ctx.plan_manager.ingest_plan.assert_called_once()


@pytest.mark.asyncio
async def test_assess_replan_continues_generate() -> None:
    ctx = _make_ctx()
    ctx.strange_loop.plan_phase.assess_status = AsyncMock(
        return_value=StatusAssessment(
            status="replan",
            goal_progress="low",
            assessment_reasoning="",
            require_goal_completion=False,
        )
    )
    out = await node_plan_assess(ctx, {})
    assert out.get("assess_route") == "continue_generate"
    assert ctx.scratch.plan_result is None
