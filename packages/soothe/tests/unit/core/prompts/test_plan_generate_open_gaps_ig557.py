"""IG-557 Phase F: gap-informed plan-generate OPEN GAPS envelope."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.protocols.planner import PlanContext

from soothe.foundation.sloop.cognition.planner import LLMPlanner
from soothe.foundation.sloop.state.schemas import (
    GoalComponentStatus,
    LoopState,
    PlanGapAnalysis,
    PlanGenerateStep,
    PlanGeneration,
    StatusAssessment,
)
from soothe.prompts import PromptBuilder
from soothe.prompts.user_message import UserMessageBuilder


def test_generate_message_includes_open_gaps_from_remaining_gaps() -> None:
    gap = PlanGapAnalysis(
        components=[
            GoalComponentStatus(component="build image", status="partial"),
        ],
        evidence_summary="Image built.",
        remaining_gaps=["start stack", "run e2e"],
        distance_from_goal="moderate",
        gap_reasoning="Build done; tests missing.",
    )
    msg = UserMessageBuilder().build_plan_generate_message(
        goal="build and test",
        assessment_status="continue",
        assessment_progress="medium",
        plan_gap=gap,
    )
    assert "OPEN GAPS:" in msg
    assert "- start stack" in msg
    assert "- run e2e" in msg
    assert msg.index("ASSESSMENT:") < msg.index("OPEN GAPS:") < msg.index("TASK:")


def test_generate_message_omits_open_gaps_when_gap_absent() -> None:
    msg = UserMessageBuilder().build_plan_generate_message(
        goal="build and test",
        assessment_status="continue",
        assessment_progress="medium",
    )
    assert "OPEN GAPS:" not in msg


def test_build_plan_messages_generate_forwards_plan_gap() -> None:
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="tests", status="not_started")],
        evidence_summary="partial",
        remaining_gaps=["run tests"],
        distance_from_goal="moderate",
        gap_reasoning="tests missing",
    )
    state = LoopState(goal="g", thread_id="t", iteration=1)
    msgs = PromptBuilder().build_plan_messages(
        "g",
        state,
        PlanContext(),
        plan_phase="generate",
        inline_assessment=StatusAssessment(status="replan", goal_progress="low"),
        plan_gap=gap,
    )
    human = msgs[-1].content
    assert "OPEN GAPS:" in human
    assert "- run tests" in human


@pytest.mark.asyncio
async def test_generate_from_assessment_passes_plan_gap_to_message_builder() -> None:
    planner = LLMPlanner(MagicMock())
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="tests", status="not_started")],
        evidence_summary="partial",
        remaining_gaps=["run tests"],
        distance_from_goal="moderate",
        gap_reasoning="tests missing",
    )
    assessment = StatusAssessment(status="replan", goal_progress="low")
    state = LoopState(goal="g", thread_id="t", iteration=1)
    plan = PlanGeneration(
        type="execute_steps",
        execution_mode="parallel",
        reasoning="I'll cover the open gaps.",
        steps=[
            PlanGenerateStep(
                id="02",
                description="Run tests",
                expected_output="passing suite",
            )
        ],
    )
    build_mock = MagicMock(return_value=[])
    planner._prompt_builder.build_plan_messages = build_mock  # type: ignore[method-assign]
    planner._generate_plan_with_response = AsyncMock(return_value=(plan, plan))  # type: ignore[method-assign]
    planner._combine_results = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]
    planner._finalize_generated_plan_result = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda *, result, **_: result
    )

    await planner.generate_from_assessment(
        "g",
        state,
        PlanContext(),
        assessment,
        plan_gap=gap,
    )

    assert build_mock.call_args.kwargs["plan_gap"] is gap
