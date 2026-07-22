"""Tests for deterministic plan reuse (keep) without plan-generate LLM call."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.protocols.planner import PlanContext

from soothe.sloop.cognition.planner import LLMPlanner
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    StatusAssessment,
    StepAction,
)


@pytest.mark.asyncio
async def test_generate_from_assessment_reuses_plan_without_llm() -> None:
    """continue + remaining steps skips plan-generate and returns keep."""
    planner = LLMPlanner(MagicMock())
    planner._generate_plan_with_response = AsyncMock()  # type: ignore[method-assign]

    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="01", description="Discover layout", expected_output="map"),
            StepAction(id="02", description="Implement fix", expected_output="patch"),
        ],
        execution_mode="parallel",
        reasoning="Two-step plan",
    )
    state = LoopState(
        goal="fix layout",
        thread_id="t1",
        iteration=1,
        current_decision=decision,
        completed_step_ids={"01"},
    )
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
