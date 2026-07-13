"""IG-557 Phase E: plan-gap-analysis routing and assess feed-forward."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from soothe.foundation.sloop.cognition.plan_step_safety import assess_respects_gap_analysis
from soothe.foundation.sloop.orchestrator.nodes.bounded_evidence_gather import (
    _should_run_gap_analysis,
)
from soothe.foundation.sloop.orchestrator.phase_scratch import LoopPhaseScratch
from soothe.foundation.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.foundation.sloop.prompts import PromptBuilder
from soothe.foundation.sloop.prompts.user_message import UserMessageBuilder
from soothe.foundation.sloop.state.schemas import (
    GoalComponentStatus,
    LoopState,
    PlanGapAnalysis,
    StatusAssessment,
    StepResult,
)
from soothe.protocols.planner import PlanContext


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
    state.add_step_result(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
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
    state.add_step_result(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
    msgs = PromptBuilder().build_plan_messages(
        "g",
        state,
        PlanContext(),
        call_kind="gap",
    )
    assert "<PLAN_GAP_ANALYSIS>" in msgs[0].content
    assert "TASK:" in msgs[-1].content
    assert "remaining_gaps" in msgs[-1].content
