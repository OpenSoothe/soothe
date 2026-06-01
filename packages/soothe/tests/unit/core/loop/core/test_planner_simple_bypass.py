"""Tests for simple-query planner bypass."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from soothe.core.loop.planning.planner import LLMPlanner
from soothe.core.loop.state.schemas import LoopState, StatusAssessment
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
            goal_progress="none",
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
    step = result.decision.steps[0]
    # Step description is the raw user goal so the LLM doesn't echo the
    # synthetic bypass prefix back as an assistant message.
    assert step.description == "count readmes"
    # The synthetic "I will complete this request directly: ..." label is
    # retained as the plan's next_action for the audit ledger / UI step header.
    assert "I will complete this request directly" in result.next_action
    assert "count readmes" in result.next_action
    # Bypass step must carry a concrete completion contract so the execute-step
    # AI message lands a "## Result" block in the ledger for plan-assess.
    assert step.expected_output is not None
    assert "## Result" in step.expected_output
    assert "MUST" in step.expected_output
