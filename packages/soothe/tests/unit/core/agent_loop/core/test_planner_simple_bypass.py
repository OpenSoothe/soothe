"""Tests for simple-query planner bypass."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from soothe.core.agent_loop.core.planner import LLMPlanner
from soothe.core.agent_loop.state.schemas import LoopState, StatusAssessment
from soothe.protocols.planner import PlanContext


@pytest.mark.asyncio
async def test_simple_query_skips_plan_generate_on_first_cycle() -> None:
    """Simple tasks should bypass plan-generate and emit one direct step."""
    planner = LLMPlanner(MagicMock())
    planner._prompt_builder.build_plan_messages = MagicMock(  # type: ignore[method-assign]
        return_value=[HumanMessage(content="assess")]
    )
    planner._assess_status = AsyncMock(  # type: ignore[method-assign]
        return_value=StatusAssessment(
            status="continue",
            goal_progress=0.1,
            confidence=0.9,
            require_goal_completion=False,
        )
    )
    planner._generate_plan = AsyncMock()  # type: ignore[method-assign]

    state = LoopState(goal="count readmes", thread_id="t1", iteration=0, max_iterations=8)
    state.intent = SimpleNamespace(task_complexity="simple")
    result = await planner.plan("count readmes", state, PlanContext(workspace="/tmp/ws"))

    planner._generate_plan.assert_not_called()
    assert result.plan_action == "new"
    assert result.decision is not None
    assert len(result.decision.steps) == 1
    assert "Complete this simple request directly" in result.decision.steps[0].description
