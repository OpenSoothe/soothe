"""Planner passes inline assess on plan-generate (assess rows excluded from projection)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.foundation.sloop.cognition.planner import LLMPlanner
from soothe.foundation.sloop.state.schemas import (
    LoopState,
    PlanGenerateStep,
    PlanGeneration,
    StatusAssessment,
)
from soothe.protocols.planner import PlanContext


@pytest.mark.asyncio
async def test_generate_from_assessment_passes_inline_assessment_when_assess_skipped() -> None:
    planner = LLMPlanner(MagicMock())
    assessment = StatusAssessment(
        status="replan",
        goal_progress="none",
        assessment_reasoning="Fresh-loop bypass: no prior execution to assess.",
    )
    state = LoopState(goal="count files", thread_id="t1", iteration=0)
    plan = PlanGeneration(
        type="execute_steps",
        execution_mode="parallel",
        reasoning="I'll start with discovery.",
        steps=[
            PlanGenerateStep(
                id="01",
                description="Discover files",
                expected_output="file list",
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

    with patch(
        "soothe.foundation.sloop.cognition.plan_step_briefs.populate_plan_generate_full_descriptions",
        side_effect=lambda p, _: p,
    ):
        await planner.generate_from_assessment(
            "count files",
            state,
            PlanContext(),
            assessment,
        )

    assert build_mock.call_args.kwargs["inline_assessment"] is assessment


@pytest.mark.asyncio
async def test_generate_from_assessment_passes_inline_assessment_when_assess_in_ledger() -> None:
    from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage

    planner = LLMPlanner(MagicMock())
    assessment = StatusAssessment(
        status="replan",
        goal_progress="low",
        assessment_reasoning="I checked prior evidence.",
    )
    state = LoopState(
        goal="count files",
        thread_id="t1",
        iteration=1,
        loop_messages=[
            LoopHumanMessage(content="assess h", phase="plan_assess", iteration=1, thread_id="t1"),
            LoopAIMessage(
                content="{'status': 'continue', 'goal_progress': 'low'}",
                phase="plan_assess",
                iteration=1,
                thread_id="t1",
            ),
        ],
    )
    plan = PlanGeneration(
        type="execute_steps",
        execution_mode="parallel",
        reasoning="I'll continue planning.",
        steps=[
            PlanGenerateStep(
                id="01",
                description="Discover files",
                expected_output="file list",
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

    with patch(
        "soothe.foundation.sloop.cognition.plan_step_briefs.populate_plan_generate_full_descriptions",
        side_effect=lambda p, _: p,
    ):
        await planner.generate_from_assessment(
            "count files",
            state,
            PlanContext(),
            assessment,
        )

    assert build_mock.call_args.kwargs["inline_assessment"] is assessment
