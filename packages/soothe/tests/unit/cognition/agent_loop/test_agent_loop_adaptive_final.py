"""AgentLoop adaptive final response wiring (IG-199)."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.cognition.agent_loop import AgentLoop
from soothe.cognition.agent_loop.schemas import PlanResult
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
        )

    mock_gr = Mock()
    mock_ckpt = Mock()
    mock_ckpt.goal_history = []

    mock_sm = Mock()
    mock_sm.load.return_value = None
    mock_sm.initialize.return_value = mock_ckpt
    mock_sm.start_new_goal.return_value = mock_gr

    mock_gcm = Mock()
    mock_gcm.get_plan_context.return_value = []

    with (
        patch(
            "soothe.cognition.agent_loop.agent_loop.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.cognition.agent_loop.agent_loop.GoalContextManager",
            return_value=mock_gcm,
        ),
        patch(
            "soothe.cognition.agent_loop.agent_loop.needs_final_thread_synthesis",
            return_value=False,
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
