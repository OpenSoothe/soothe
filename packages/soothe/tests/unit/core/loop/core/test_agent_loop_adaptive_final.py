"""AgentLoop adaptive final response wiring (IG-199, IG-299)."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.config import SootheConfig
from soothe.core.loop import AgentLoop
from soothe.core.loop.state.schemas import StatusAssessment


def _make_mock_core_with_checkpointer() -> Mock:
    """Create mock CoreAgent with graph.checkpointer as AsyncMock returning None.

    Without this, node_iteration_start's anchor_manager.capture_iteration_start_anchor
    tries to await checkpointer.aget_tuple(config), causing TypeError on regular Mock.
    """
    mock_core = Mock()
    mock_graph = Mock()
    mock_graph.checkpointer = AsyncMock(return_value=None)
    mock_core.graph = mock_graph
    return mock_core


@pytest.mark.asyncio
async def test_done_skips_second_core_astream_when_policy_reuses_execute() -> None:
    """When synthesis is skipped, CoreAgent astream must not run for the final report."""
    calls = 0

    async def counting_astream(*args, **kwargs):  # noqa: ARG002
        nonlocal calls
        calls += 1
        if False:
            yield None

    mock_core = _make_mock_core_with_checkpointer()
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
    mock_sm.close = AsyncMock()

    mock_gcm = Mock()
    mock_gcm.get_plan_context = AsyncMock(return_value=[])

    mock_anchor_mgr = Mock()
    mock_anchor_mgr.capture_iteration_start_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()

    with (
        patch(
            "soothe.core.loop.engine.agent_loop.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.core.loop.engine.agent_loop.GoalContextManager",
            return_value=mock_gcm,
        ),
        patch(
            "soothe.core.loop.engine.agent_loop.CheckpointAnchorManager",
            return_value=mock_anchor_mgr,
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

    mock_core = _make_mock_core_with_checkpointer()
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
    mock_sm.close = AsyncMock()

    mock_gcm = Mock()
    mock_gcm.get_plan_context = AsyncMock(return_value=[])

    mock_anchor_mgr = Mock()
    mock_anchor_mgr.capture_iteration_start_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()

    with (
        patch(
            "soothe.core.loop.engine.agent_loop.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.core.loop.engine.agent_loop.GoalContextManager",
            return_value=mock_gcm,
        ),
        patch(
            "soothe.core.loop.engine.agent_loop.CheckpointAnchorManager",
            return_value=mock_anchor_mgr,
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
    mock_core = _make_mock_core_with_checkpointer()
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
    mock_sm.close = AsyncMock()

    mock_gcm = Mock()
    mock_gcm.get_plan_context = AsyncMock(return_value=[])

    mock_anchor_mgr = Mock()
    mock_anchor_mgr.capture_iteration_start_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()

    with (
        patch(
            "soothe.core.loop.engine.agent_loop.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.core.loop.engine.agent_loop.GoalContextManager",
            return_value=mock_gcm,
        ),
        patch(
            "soothe.core.loop.engine.agent_loop.CheckpointAnchorManager",
            return_value=mock_anchor_mgr,
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


@pytest.mark.asyncio
async def test_main_thread_id_normalizes_to_loop_id_on_initialize() -> None:
    """RFC-223: AgentLoop main thread id must align to loop_id."""
    mock_core = _make_mock_core_with_checkpointer()
    mock_core.astream = AsyncMock()

    mock_gr = Mock()
    mock_gr.loop_messages = []
    mock_ckpt = Mock()
    mock_ckpt.goal_history = []
    mock_ckpt.loop_messages = []
    mock_ckpt.status = "idle"
    mock_ckpt.current_thread_id = "legacy-thread"
    mock_ckpt.thread_ids = ["legacy-thread"]

    mock_sm = Mock()
    mock_sm.loop_id = "loop-test"
    mock_sm.load = AsyncMock(return_value=None)
    mock_sm.initialize = AsyncMock(return_value=mock_ckpt)
    mock_sm.start_new_goal = Mock(return_value=mock_gr)
    mock_sm.save = AsyncMock()
    mock_sm.record_iteration = AsyncMock()
    mock_sm.finalize_goal = AsyncMock()
    mock_sm.close = AsyncMock()

    mock_gcm = Mock()
    mock_gcm.get_plan_context = AsyncMock(return_value=[])

    mock_anchor_mgr = Mock()
    mock_anchor_mgr.capture_iteration_start_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()

    with (
        patch(
            "soothe.core.loop.engine.agent_loop.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.core.loop.engine.agent_loop.GoalContextManager",
            return_value=mock_gcm,
        ),
        patch(
            "soothe.core.loop.engine.agent_loop.CheckpointAnchorManager",
            return_value=mock_anchor_mgr,
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

        _ = [
            evt
            async for evt in loop.run_with_progress(
                goal="simple goal",
                thread_id="thread-a",
                max_iterations=8,
            )
        ]

    mock_sm.initialize.assert_awaited_once_with("loop-test", 8)
