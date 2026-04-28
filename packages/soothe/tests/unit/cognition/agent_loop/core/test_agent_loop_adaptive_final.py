"""AgentLoop adaptive final response wiring (IG-199, IG-299)."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.cognition.agent_loop import AgentLoop
from soothe.cognition.agent_loop.state.schemas import PlanResult
from soothe.config import SootheConfig


@pytest.mark.asyncio
async def test_done_skips_second_core_astream_when_policy_reuses_execute() -> None:
    """When synthesis is skipped, CoreAgent astream must not run for the final report."""
    calls = 0

    async def counting_astream(*args, **kwargs):  # noqa: ARG002
        nonlocal calls
        calls += 1
        if False:
            yield None

    mock_core = Mock()
    mock_core.astream = counting_astream

    async def fake_plan(goal, state, context):  # noqa: ARG001
        return PlanResult(
            status="done",
            evidence_summary="evidence body",
            goal_progress=1.0,
            confidence=0.9,
            reasoning="",
            next_action="done",
            plan_action="new",
            full_output="from plan full_output",
            require_goal_completion=False,  # IG-299: Planner says skip synthesis
        )

    mock_gr = Mock()
    mock_ckpt = Mock()
    mock_ckpt.goal_history = []

    mock_sm = Mock()
    mock_sm.load = AsyncMock(return_value=None)
    mock_sm.initialize = AsyncMock(return_value=mock_ckpt)
    mock_sm.start_new_goal = Mock(return_value=mock_gr)
    mock_sm.save = AsyncMock()
    mock_sm.record_iteration = AsyncMock()
    mock_sm.finalize_goal = AsyncMock()

    mock_gcm = Mock()
    mock_gcm.get_plan_context = AsyncMock(return_value=[])

    with (
        patch(
            "soothe.cognition.agent_loop.core.agent_loop.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.cognition.agent_loop.core.agent_loop.GoalContextManager",
            return_value=mock_gcm,
        ),
    ):
        loop = AgentLoop(mock_core, AsyncMock(), SootheConfig())
        loop.plan_phase.plan = fake_plan

        events = [
            evt
            async for evt in loop.run_with_progress(
                goal="simple goal",
                thread_id="thread-a",
            )
        ]

    assert events
    assert calls == 0, "final-report CoreAgent astream should not run when reusing Execute text"


@pytest.mark.asyncio
async def test_done_skips_goal_completion_synthesis_when_direct_return_selected() -> None:
    """Direct goal completion should bypass synthesis when planner recommends it."""
    calls = 0

    async def counting_astream(*args, **kwargs):  # noqa: ARG002
        nonlocal calls
        calls += 1
        if False:
            yield None

    mock_core = Mock()
    mock_core.astream = counting_astream

    async def fake_plan(goal, state, context):  # noqa: ARG001
        return PlanResult(
            status="done",
            evidence_summary="evidence body",
            goal_progress=1.0,
            confidence=0.9,
            reasoning="",
            next_action="done",
            plan_action="new",
            full_output="from plan full_output",
            require_goal_completion=False,  # IG-299: Planner says skip synthesis
        )

    mock_gr = Mock()
    mock_ckpt = Mock()
    mock_ckpt.goal_history = []

    mock_sm = Mock()
    mock_sm.load = AsyncMock(return_value=None)
    mock_sm.initialize = AsyncMock(return_value=mock_ckpt)
    mock_sm.start_new_goal = Mock(return_value=mock_gr)
    mock_sm.save = AsyncMock()
    mock_sm.record_iteration = AsyncMock()
    mock_sm.finalize_goal = AsyncMock()

    mock_gcm = Mock()
    mock_gcm.get_plan_context = AsyncMock(return_value=[])

    with (
        patch(
            "soothe.cognition.agent_loop.core.agent_loop.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.cognition.agent_loop.core.agent_loop.GoalContextManager",
            return_value=mock_gcm,
        ),
        patch(
            "soothe.cognition.agent_loop.policies.goal_completion_policy.determine_completion_action",
            return_value=("skip", "from plan full_output"),
        ),
    ):
        loop = AgentLoop(mock_core, AsyncMock(), SootheConfig())
        loop.plan_phase.plan = fake_plan

        events = [
            evt
            async for evt in loop.run_with_progress(
                goal="simple goal",
                thread_id="thread-a",
            )
        ]

    assert events
    assert calls == 0, "synthesis should not run when planner recommends direct return"
