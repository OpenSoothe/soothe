"""AgentLoop adaptive final response wiring (IG-199, IG-299)."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.config import SootheConfig
from soothe.core.agent_loop import AgentLoop
from soothe.core.agent_loop.state.schemas import StatusAssessment


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

    mock_gr = Mock()
    mock_gr.loop_messages = []  # RFC-214: Required list field for LoopState
    mock_ckpt = Mock()
    mock_ckpt.goal_history = []
    mock_ckpt.loop_messages = []  # RFC-214: Required list field for LoopState

    mock_sm = Mock()
    mock_sm.loop_id = "loop-test"
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
            "soothe.core.agent_loop.core.agent_loop.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.core.agent_loop.core.agent_loop.GoalContextManager",
            return_value=mock_gcm,
        ),
    ):
        loop = AgentLoop(mock_core, AsyncMock(), SootheConfig())
        loop.plan_phase.assess_status = AsyncMock(
            return_value=StatusAssessment(
                status="done",
                goal_progress="complete",
                require_goal_completion=False,
            ),
        )

        events = [
            evt
            async for evt in loop.run_with_progress(
                goal="simple goal",
                thread_id="thread-a",
            )
        ]

    assert events
    assert calls == 0, "final-report CoreAgent astream should not run when reusing ledger text"


@pytest.mark.asyncio
async def test_done_skips_goal_completion_synthesis_when_ledger_direct_selected() -> None:
    """Ledger-direct goal completion should bypass synthesis when planner recommends it."""
    calls = 0

    async def counting_astream(*args, **kwargs):  # noqa: ARG002
        nonlocal calls
        calls += 1
        if False:
            yield None

    mock_core = Mock()
    mock_core.astream = counting_astream

    mock_gr = Mock()
    mock_gr.loop_messages = []  # RFC-214: Required list field for LoopState
    mock_ckpt = Mock()
    mock_ckpt.goal_history = []
    mock_ckpt.loop_messages = []  # RFC-214: Required list field for LoopState

    mock_sm = Mock()
    mock_sm.loop_id = "loop-test"
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
            "soothe.core.agent_loop.core.agent_loop.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.core.agent_loop.core.agent_loop.GoalContextManager",
            return_value=mock_gcm,
        ),
        patch(
            "soothe.core.agent_loop.graph.nodes.goal_completion.determine_completion_action",
            return_value="ledger_direct",
        ),
        patch(
            "soothe.core.agent_loop.graph.nodes.goal_completion.last_ledger_ai_content",
            return_value="from ledger",
        ),
    ):
        loop = AgentLoop(mock_core, AsyncMock(), SootheConfig())
        loop.plan_phase.assess_status = AsyncMock(
            return_value=StatusAssessment(
                status="done",
                goal_progress="complete",
                require_goal_completion=False,
            ),
        )

        events = [
            evt
            async for evt in loop.run_with_progress(
                goal="simple goal",
                thread_id="thread-a",
            )
        ]

    assert events
    assert calls == 0, "synthesis should not run when planner recommends ledger direct"
    completed = [e for e in events if e[0] == "completed"]
    assert len(completed) == 1


@pytest.mark.asyncio
async def test_completed_payload_for_summary_path() -> None:
    """Summary path may emit runner goal_completion chunk."""
    mock_core = Mock()
    mock_core.astream = AsyncMock()

    mock_gr = Mock()
    mock_gr.loop_messages = []  # RFC-214: Required list field for LoopState
    mock_ckpt = Mock()
    mock_ckpt.goal_history = []
    mock_ckpt.loop_messages = []  # RFC-214: Required list field for LoopState

    mock_sm = Mock()
    mock_sm.loop_id = "loop-test"
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
            "soothe.core.agent_loop.core.agent_loop.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.core.agent_loop.core.agent_loop.GoalContextManager",
            return_value=mock_gcm,
        ),
        patch(
            "soothe.core.agent_loop.graph.nodes.goal_completion.determine_completion_action",
            return_value="summary",
        ),
        patch(
            "soothe.core.agent_loop.graph.nodes.goal_completion.generate_user_fallback_summary",
            return_value="fallback summary",
        ),
    ):
        loop = AgentLoop(mock_core, AsyncMock(), SootheConfig())
        loop.plan_phase.assess_status = AsyncMock(
            return_value=StatusAssessment(
                status="done",
                goal_progress="complete",
                require_goal_completion=False,
            ),
        )

        events = [
            evt
            async for evt in loop.run_with_progress(
                goal="simple goal",
                thread_id="thread-a",
            )
        ]

    completed = [e for e in events if e[0] == "completed"]
    assert len(completed) == 1
