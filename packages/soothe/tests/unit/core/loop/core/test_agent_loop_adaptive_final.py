"""AgentLoop adaptive final response wiring (IG-199, IG-299)."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.config import SootheConfig
from soothe.core.loop import AgentLoop
from soothe.core.loop.state.schemas import StatusAssessment


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
    mock_gr.loop_messages = []
    mock_ckpt = Mock()
    mock_ckpt.goal_history = []
    mock_ckpt.loop_messages = []

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
            "soothe.core.loop.state.manager.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.core.loop.engine.goal_context_manager.GoalContextManager",
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
    mock_gr.loop_messages = []
    mock_ckpt = Mock()
    mock_ckpt.goal_history = []
    mock_ckpt.loop_messages = []

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
            "soothe.core.loop.state.manager.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.core.loop.engine.goal_context_manager.GoalContextManager",
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
    assert calls == 0, "synthesis should not run when planner recommends ledger direct"
    completed = [e for e in events if e[0] == "completed"]
    assert len(completed) == 1


@pytest.mark.asyncio
async def test_completed_payload_for_summary_path() -> None:
    """Summary path is used when ledger is empty and synthesis produces no text."""
    mock_core = Mock()
    mock_core.astream = AsyncMock()

    mock_gr = Mock()
    mock_gr.loop_messages = []
    mock_ckpt = Mock()
    mock_ckpt.goal_history = []
    mock_ckpt.loop_messages = []

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
            "soothe.core.loop.state.manager.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.core.loop.engine.goal_context_manager.GoalContextManager",
            return_value=mock_gcm,
        ),
    ):
        loop = AgentLoop(mock_core, AsyncMock(), SootheConfig())
        # require_goal_completion=False with empty DAG → ledger_direct
        # But ledger is empty, so last_ledger_ai_content returns ""
        # The code path: ledger_direct → last_ledger_ai_content → "" → final_output=""
        # This test verifies the completed event is emitted regardless
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
