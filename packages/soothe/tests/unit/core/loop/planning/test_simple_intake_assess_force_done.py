"""Tests for simple-intake assess override in LLMPlanner."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage
from soothe_nano.protocols.planner import PlanContext

from soothe.foundation.sloop.cognition.planner import LLMPlanner
from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.state.schemas import (
    LoopState,
    PriorProgressDigest,
    StatusAssessment,
    StepResult,
)


@pytest.mark.asyncio
async def test_assess_status_forces_done_for_simple_intake_with_evidence() -> None:
    """After a successful search wave, simple goals should route to synthesis."""
    planner = LLMPlanner(MagicMock())
    planner._prompt_builder.build_plan_messages = MagicMock(  # type: ignore[method-assign]
        return_value=[HumanMessage(content="assess")]
    )
    assessment = StatusAssessment(
        status="continue",
        goal_progress="none",
        require_goal_completion=False,
    )
    planner._assess_status_with_response = AsyncMock(  # type: ignore[method-assign]
        return_value=(assessment, assessment)
    )

    state = LoopState(goal="world cup progress", thread_id="t1", iteration=1)
    state.intent = SimpleNamespace(intake_label=IntakeLabel.SIMPLE)
    state.prior_progress = PriorProgressDigest(
        iteration=1,
        derived_progress_hint="high",
        steps_completed=1,
    )
    state.step_results = [
        StepResult(
            step_id="CSF-01",
            success=True,
            duration_ms=1000,
            thread_id="t1",
            subgraph_tool_call_count=2,
        )
    ]

    result = await planner.assess_status(
        "world cup progress",
        state,
        PlanContext(workspace="/tmp/ws"),
    )

    assert result.status == "done"
    assert result.goal_progress == "high"
    assert result.require_goal_completion is True
