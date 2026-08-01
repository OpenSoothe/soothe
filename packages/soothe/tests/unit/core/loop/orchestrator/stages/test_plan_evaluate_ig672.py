"""IG-672: evaluate inventory soft-fail, routing helpers, and assess feed-forward."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe_nano.utils.llm.structured import StructuredOutputError
from soothe_sdk.protocols.planner import PlanContext

from soothe.sloop.cognition.plan_step_safety import assess_respects_gap_analysis
from soothe.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.prompts import PromptBuilder
from soothe.sloop.prompts.user_message import UserMessageBuilder
from soothe.sloop.stages.plan.evaluate import (
    node_plan_evaluate,
    reduce_component_legs,
    run_inventory,
    should_run_inventory,
)
from soothe.sloop.state.schemas import (
    GoalComponentStatus,
    LoopState,
    PlanGapAnalysis,
    StatusAssessment,
    StepExecutionRecord,
)


def test_should_skip_inventory_at_iter0_without_execution() -> None:
    state = LoopState(goal="g", thread_id="t", iteration=0)
    ctx = LoopRuntimeContext(
        strange_loop=MagicMock(config=None),
        state_manager=MagicMock(),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=None,
        goal_record=None,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=state,
        emit=AsyncMock(),
        scratch=LoopPhaseScratch(),
        ce=None,
        ce_goal_id=None,
    )
    assert should_run_inventory(ctx) is False


def test_should_run_inventory_on_mid_goal() -> None:
    state = LoopState(goal="g", thread_id="t", iteration=1)
    state.add_step_result(
        StepExecutionRecord(step_id="01", success=True, duration_ms=1, thread_id="t")
    )
    ctx = LoopRuntimeContext(
        strange_loop=MagicMock(config=None),
        state_manager=MagicMock(),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=None,
        goal_record=None,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        loop_state=state,
        emit=AsyncMock(),
        scratch=LoopPhaseScratch(),
        ce=None,
        ce_goal_id=None,
    )
    assert should_run_inventory(ctx) is True


def test_assess_envelope_includes_gap_analysis_block() -> None:
    gap = PlanGapAnalysis(
        components=[
            GoalComponentStatus(
                component="build image",
                status="partial",
                evidence="step 01 build ok",
                gap="e2e missing",
            )
        ],
        evidence_summary="Image built locally.",
        remaining_gaps=["run e2e"],
        distance_from_goal="moderate",
        gap_reasoning="Build done; tests not run.",
    )
    msg = UserMessageBuilder().build_plan_assess_message_v2(goal="build and test", plan_gap=gap)
    assert "GAP ANALYSIS:" in msg
    assert "distance_from_goal: moderate" in msg
    assert "build image" in msg


def test_plan_gap_allows_long_component_evidence() -> None:
    long_evidence = "x" * 1800
    long_gap = "y" * 260
    gap = PlanGapAnalysis(
        components=[
            GoalComponentStatus(
                component="deploy/docs ref alignment",
                status="partial",
                evidence=long_evidence,
                gap=long_gap,
            )
        ],
        evidence_summary="partial",
        remaining_gaps=["final pass"],
        distance_from_goal="moderate",
        gap_reasoning="still updating references",
    )
    assert gap.components[0].evidence == long_evidence
    assert gap.components[0].gap == long_gap


def test_assess_respects_gap_rejects_complete() -> None:
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="tests", status="not_started")],
        evidence_summary="partial",
        remaining_gaps=["run tests"],
        distance_from_goal="moderate",
        gap_reasoning="tests missing",
    )
    assessment = StatusAssessment(status="done", goal_progress="complete")
    assert assess_respects_gap_analysis(assessment, gap) is False


def test_build_plan_messages_gap_kind_uses_gap_instructions() -> None:
    state = LoopState(goal="g", thread_id="t", iteration=1)
    state.add_step_result(
        StepExecutionRecord(step_id="01", success=True, duration_ms=1, thread_id="t")
    )
    msgs = PromptBuilder().build_plan_messages(
        "g",
        state,
        PlanContext(),
        call_kind="gap",
    )
    assert "<PLAN_GAP_ANALYSIS>" in msgs[0].content
    assert "TASK:" in msgs[-1].content
    assert "remaining_gaps" in msgs[-1].content


def test_reduce_missing_legs_blocks_at_goal() -> None:
    gap = reduce_component_legs(
        ["a", "b"],
        [
            GoalComponentStatus(component="a", status="satisfied", evidence="ok"),
            None,
        ],
    )
    assert gap is not None
    assert gap.distance_from_goal != "at_goal"
    assert gap.components[1].status == "not_started"


def test_reduce_all_satisfied_is_at_goal() -> None:
    gap = reduce_component_legs(
        ["a", "b"],
        [
            GoalComponentStatus(component="a", status="satisfied"),
            GoalComponentStatus(component="b", status="satisfied"),
        ],
    )
    assert gap is not None
    assert gap.distance_from_goal == "at_goal"


def _eval_ctx(*, plan_phase: MagicMock) -> LoopRuntimeContext:
    strange_loop = MagicMock()
    strange_loop.plan_phase = plan_phase
    strange_loop._build_plan_context = MagicMock(return_value=MagicMock())
    strange_loop.config = MagicMock()
    loop = MagicMock()
    loop.plan_evaluate_gap_mode = "sequential"
    loop.plan_evaluate_gap_wall_clock_seconds = 90.0
    loop.plan_evaluate_gap_leg_timeout_seconds = 45.0
    loop.plan_evaluate_gap_max_concurrency = 4
    loop.plan_evaluate_gap_min_facets = 2
    strange_loop.config.agent.loop = loop
    state = LoopState(goal="verify readiness", thread_id="t-e217", iteration=2)
    state.add_step_result(
        StepExecutionRecord(step_id="01", success=True, duration_ms=1, thread_id="t")
    )
    return LoopRuntimeContext(
        strange_loop=strange_loop,
        state_manager=MagicMock(),
        anchor_manager=MagicMock(),
        goal_context_manager=MagicMock(),
        plan_manager=MagicMock(),
        checkpoint=None,
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
async def test_inventory_soft_fails_structured_output_error() -> None:
    plan_phase = MagicMock()
    plan_phase.analyze_plan_gap = AsyncMock(
        side_effect=StructuredOutputError(
            "structured_output_validation_failed: 'component' is a required property"
        )
    )
    ctx = _eval_ctx(plan_phase=plan_phase)

    gap = await run_inventory(ctx)

    assert gap is None
    plan_phase.analyze_plan_gap.assert_awaited_once()


@pytest.mark.asyncio
async def test_inventory_soft_fails_on_timeout() -> None:
    async def _hang(*_a: object, **_k: object) -> None:
        await asyncio.sleep(3600)

    plan_phase = MagicMock()
    plan_phase.analyze_plan_gap = AsyncMock(side_effect=_hang)
    ctx = _eval_ctx(plan_phase=plan_phase)
    ctx.strange_loop.config.agent.loop.plan_evaluate_gap_wall_clock_seconds = 0.05

    gap = await run_inventory(ctx)

    assert gap is None


@pytest.mark.asyncio
async def test_inventory_stashes_via_evaluate_node() -> None:
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="api", status="satisfied")],
        evidence_summary="ok",
        remaining_gaps=[],
        distance_from_goal="at_goal",
        gap_reasoning="complete",
    )
    plan_phase = MagicMock()
    plan_phase.analyze_plan_gap = AsyncMock(return_value=gap)
    plan_phase.assess_status = AsyncMock(
        return_value=StatusAssessment(status="continue", goal_progress="medium")
    )
    ctx = _eval_ctx(plan_phase=plan_phase)

    with patch(
        "soothe.sloop.stages.plan.evaluate.node_plan_assess",
        new=AsyncMock(return_value={"assess_route": "continue_generate"}),
    ) as assess:
        result = await node_plan_evaluate(ctx, {})

    assert result.get("assess_route") == "continue_generate"
    assert ctx.scratch.plan_gap is gap
    assess.assert_awaited_once()
