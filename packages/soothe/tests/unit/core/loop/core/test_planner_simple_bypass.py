"""Tests for the planner after RFC-630 removed the simple-query bypass.

The legacy in-planner simple-query bypass (prefixed 1-step plan, skipped
plan-generate) is removed (RFC-630). Single-step goals are now handled by the
``trivial`` intake label via ``build_trivial_plan`` in ``init_or_resume``;
the ``simple`` label uses ``generate_lightweight``. The planner's
``plan()``/``generate_from_assessment()`` no longer short-circuit on
``task_complexity == "simple"`` — they always run the plan-generate LLM call.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from soothe.foundation.loop.cognition.planner import LLMPlanner
from soothe.foundation.loop.state.schemas import LoopState, StatusAssessment
from soothe.protocols.planner import PlanContext


@pytest.mark.asyncio
async def test_simple_query_no_longer_bypasses_plan_generate() -> None:
    """RFC-630: ``task_complexity == "simple"`` no longer skips plan-generate.

    The planner must run the plan-generate LLM call (no synthetic prefixed
    1-step plan). The trivial/simple branches are handled upstream by the
    intake routing, not by the planner.
    """
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
    # Stub _generate_plan to return a minimal plan result without a real LLM call.
    from soothe.foundation.loop.state.schemas import AgentDecision, PlanResult, StepAction

    planner._generate_plan = AsyncMock(  # type: ignore[method-assign]
        return_value=PlanResult(
            status="continue",
            goal_progress="none",
            plan_action="new",
            decision=AgentDecision(
                type="execute_steps",
                execution_mode="parallel",
                reasoning="plan-generate ran",
                steps=[StepAction(description="count readmes")],
            ),
            next_action="count readmes",
        )
    )

    state = LoopState(goal="count readmes", thread_id="t1", iteration=0, max_iterations=8)
    state.intent = SimpleNamespace(task_complexity="simple")
    result = await planner.plan("count readmes", state, PlanContext(workspace="/tmp/ws"))

    # plan-generate WAS called — the bypass is gone.
    planner._generate_plan.assert_awaited()
    assert result.decision is not None
    # No synthetic prefix in the plan output.
    assert "I will complete this goal directly" not in result.next_action
