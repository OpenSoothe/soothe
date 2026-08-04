"""Tests for deterministic plan reuse (keep) without plan-generate LLM call."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.protocols.planner import PlanContext

from soothe.sloop.cognition.planner import LLMPlanner
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanGenerateStep,
    PlanGeneration,
    StatusAssessment,
    StepAction,
    StepExecutionRecord,
)


def _remaining_two_step_state(*, last_failed: bool = False) -> LoopState:
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="01", description="Discover layout", expected_output="map"),
            StepAction(id="02", description="Implement fix", expected_output="patch"),
        ],
        execution_mode="dependency",
        reasoning="Two-step plan",
    )
    state = LoopState(
        goal="fix layout",
        thread_id="t1",
        iteration=1,
        current_decision=decision,
        completed_step_ids={"01"},
    )
    if last_failed:
        state.add_step_result(
            StepExecutionRecord(
                step_id="01",
                success=True,
                duration_ms=10,
                thread_id="t1",
            )
        )
        state.add_step_result(
            StepExecutionRecord(
                step_id="02",
                success=False,
                error="CoreAgent stream stalled for 300s without graph chunks",
                error_type="timeout",
                duration_ms=300_000,
                thread_id="t1",
            )
        )
    return state


@pytest.mark.asyncio
async def test_generate_from_assessment_reuses_plan_without_llm() -> None:
    """continue + remaining steps skips plan-generate and returns keep."""
    planner = LLMPlanner(MagicMock())
    planner._generate_plan_with_response = AsyncMock()  # type: ignore[method-assign]

    state = _remaining_two_step_state(last_failed=False)
    assessment = StatusAssessment(status="continue", goal_progress="medium")

    result = await planner.generate_from_assessment(
        "fix layout",
        state,
        PlanContext(),
        assessment,
    )

    planner._generate_plan_with_response.assert_not_called()
    assert result.plan_action == "keep"
    assert result.decision is None
    assert "continue" in result.next_action.lower()


@pytest.mark.asyncio
async def test_generate_from_assessment_rejects_keep_after_failed_step() -> None:
    """IG-683: failed last wave must not short-circuit to keep."""
    planner = LLMPlanner(MagicMock())
    plan_generation = PlanGeneration(
        type="execute_steps",
        steps=[
            PlanGenerateStep(
                id="03",
                description="Retry with narrower scope after stall",
                expected_output="ok",
            )
        ],
        execution_mode="parallel",
    )
    planner._prompt_builder.build_plan_messages = MagicMock(  # type: ignore[method-assign]
        return_value=[]
    )
    planner._generate_plan_with_response = AsyncMock(  # type: ignore[method-assign]
        return_value=(plan_generation, plan_generation)
    )
    planner._finalize_generated_plan_result = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda result, **_: result
    )

    state = _remaining_two_step_state(last_failed=True)
    assessment = StatusAssessment(status="continue", goal_progress="medium")

    result = await planner.generate_from_assessment(
        "fix layout",
        state,
        PlanContext(),
        assessment,
    )

    planner._generate_plan_with_response.assert_called_once()
    assert assessment.status == "replan"
    assert result.plan_action == "new"
    assert result.decision is not None
