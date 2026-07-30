"""IG-557 / IG-593: plan-gap-analysis routing, soft-fail, and assess feed-forward."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_nano.utils.llm.structured import StructuredOutputError
from soothe_sdk.protocols.planner import PlanContext

from soothe.sloop.cognition.plan_step_safety import assess_respects_gap_analysis
from soothe.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.prompts import PromptBuilder
from soothe.sloop.prompts.user_message import UserMessageBuilder
from soothe.sloop.stages.plan.analyze_gaps import (
    node_plan_gap_analysis,
)
from soothe.sloop.stages.plan.gather_evidence import (
    _should_run_gap_analysis,
)
from soothe.sloop.state.schemas import (
    GoalComponentStatus,
    LoopState,
    PlanGapAnalysis,
    StatusAssessment,
    StepExecutionRecord,
)


def test_should_skip_gap_at_iter0_without_execution() -> None:
    state = LoopState(goal="g", thread_id="t", iteration=0)
    ctx = LoopRuntimeContext(
        strange_loop=MagicMock(
            config=MagicMock(agent=MagicMock(loop=MagicMock(plan_gap_analysis_enabled=True)))
        ),
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
    assert _should_run_gap_analysis(ctx) is False


def test_should_run_gap_on_mid_goal() -> None:
    state = LoopState(goal="g", thread_id="t", iteration=1)
    state.add_step_result(
        StepExecutionRecord(step_id="01", success=True, duration_ms=1, thread_id="t")
    )
    ctx = LoopRuntimeContext(
        strange_loop=MagicMock(
            config=MagicMock(agent=MagicMock(loop=MagicMock(plan_gap_analysis_enabled=True)))
        ),
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
    assert _should_run_gap_analysis(ctx) is True


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


def test_plan_gap_allows_long_gap_reasoning() -> None:
    gap_reasoning = (
        "The technical capability (script logic) is confirmed 'satisfied' via the patch in step 1. "
        "The failure is purely environmental: the feature flag (cert file) required by the template "
        "engine is missing. Once a placeholder cert file is placed and the script is re-run, the "
        "verification should succeed immediately."
    )
    assert len(gap_reasoning) == 309
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="verification", status="partial")],
        evidence_summary="Script logic patched.",
        remaining_gaps=["add cert placeholder"],
        distance_from_goal="near",
        gap_reasoning=gap_reasoning,
    )
    assert gap.gap_reasoning == gap_reasoning


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


def _gap_node_ctx(*, plan_phase: MagicMock) -> LoopRuntimeContext:
    strange_loop = MagicMock()
    strange_loop.plan_phase = plan_phase
    strange_loop._build_plan_context = MagicMock(return_value=MagicMock())
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
        loop_state=LoopState(goal="verify readiness", thread_id="t-e217", iteration=2),
        emit=AsyncMock(),
        scratch=LoopPhaseScratch(),
        ce=None,
        ce_goal_id=None,
    )


@pytest.mark.asyncio
async def test_node_soft_fails_structured_output_error() -> None:
    plan_phase = MagicMock()
    plan_phase.analyze_plan_gap = AsyncMock(
        side_effect=StructuredOutputError(
            "structured_output_validation_failed: 'component' is a required property"
        )
    )
    ctx = _gap_node_ctx(plan_phase=plan_phase)

    result = await node_plan_gap_analysis(ctx, {})

    assert result == {}
    assert ctx.scratch.plan_gap is None
    plan_phase.analyze_plan_gap.assert_awaited_once()


@pytest.mark.asyncio
async def test_node_stashes_gap_on_success() -> None:
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="api", status="satisfied")],
        evidence_summary="ok",
        remaining_gaps=[],
        distance_from_goal="at_goal",
        gap_reasoning="complete",
    )
    plan_phase = MagicMock()
    plan_phase.analyze_plan_gap = AsyncMock(return_value=gap)
    ctx = _gap_node_ctx(plan_phase=plan_phase)

    result = await node_plan_gap_analysis(ctx, {})

    assert result == {}
    assert ctx.scratch.plan_gap is gap
