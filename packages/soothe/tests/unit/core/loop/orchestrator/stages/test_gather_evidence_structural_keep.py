"""gather_evidence structural keep and simple gap skip (IG-671)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.intention.models import TaskComplexity
from soothe_sdk.protocols.planner import PlanContext

from soothe.sloop.intention.models import IntakeLabel, IntentClassification
from soothe.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.stages.plan.gather_evidence import node_bounded_evidence_gather
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    StepAction,
    StepExecutionRecord,
)


def _make_ctx(
    *, iteration: int = 1, intake: IntakeLabel = IntakeLabel.COMPLEX
) -> LoopRuntimeContext:
    state = LoopState(
        goal="ship feature",
        thread_id="t1",
        iteration=iteration,
        intent=IntentClassification(
            intake_label=intake,
            task_complexity=(
                TaskComplexity.SIMPLE if intake == IntakeLabel.SIMPLE else TaskComplexity.COMPLEX
            ),
        ),
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

    loop_cfg = MagicMock()
    loop_cfg.plan_structural_keep_enabled = True
    loop_cfg.plan_structural_keep_max_streak = 3
    loop_cfg.plan_gap_analysis_enabled = True
    loop_cfg.plan_gap_skip_simple_mid_loop = True

    strange_loop = MagicMock()
    strange_loop._build_plan_context.return_value = PlanContext()
    strange_loop.plan_phase.finalize_plan_result = MagicMock(side_effect=lambda **kw: kw["result"])
    strange_loop.config = MagicMock()
    strange_loop.config.agent.loop = loop_cfg

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
        ce=MagicMock(),
        ce_goal_id="g1",
    )


@pytest.mark.asyncio
async def test_structural_keep_routes_to_keep_plan() -> None:
    ctx = _make_ctx()
    out = await node_bounded_evidence_gather(ctx, {})
    assert out.get("evidence_gather_route") == "keep_plan"
    assert ctx.scratch.plan_result is not None
    assert ctx.scratch.plan_result.plan_action == "keep"
    assert ctx.loop_state.structural_keep_streak == 1


@pytest.mark.asyncio
async def test_failed_last_step_skips_structural_keep() -> None:
    ctx = _make_ctx()
    ctx.loop_state.step_results[-1].success = False
    out = await node_bounded_evidence_gather(ctx, {})
    assert out.get("evidence_gather_route") == "analyze_gaps"
    assert ctx.loop_state.structural_keep_streak == 0


@pytest.mark.asyncio
async def test_simple_mid_loop_skips_gap_when_keep_disabled() -> None:
    ctx = _make_ctx(intake=IntakeLabel.SIMPLE)
    ctx.strange_loop.config.agent.loop.plan_structural_keep_enabled = False
    out = await node_bounded_evidence_gather(ctx, {})
    assert out.get("evidence_gather_route") == "assess"
