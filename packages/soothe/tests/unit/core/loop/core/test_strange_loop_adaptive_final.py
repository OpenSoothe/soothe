"""StrangeLoop adaptive final response wiring (IG-199, IG-299)."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.config import SootheConfig
from soothe.foundation.context.planning.models import CompletionStrategy
from soothe.foundation.sloop import StrangeLoop
from soothe.foundation.sloop.state.schemas import PlanResult


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


def _make_done_plan_result() -> PlanResult:
    """Create a done PlanResult for tests (IG-476)."""
    return PlanResult(
        status="done",
        goal_progress="complete",
        plan_action="keep",
        decision=None,
        next_action="Goal achieved successfully",
        require_goal_completion=False,
        assessment_reasoning="",
        plan_reasoning="",
    )


def _make_mock_ce() -> Mock:
    """Build a mock ContextEngine with all required attributes."""
    mock_ce = Mock()
    mock_goal = Mock()
    mock_goal.id = "test-goal-id"
    # Mock goal.steps.nodes for step_results property iteration
    mock_goal.steps = Mock()
    mock_goal.steps.nodes = {}
    mock_ce.load = AsyncMock(return_value=False)
    mock_ce.create_goal = AsyncMock(return_value=mock_goal)
    mock_ce.activate_goal = AsyncMock()
    mock_ce.save = AsyncMock()
    mock_ce.complete_goal = AsyncMock()
    mock_ce.finalize_goal = AsyncMock()  # Called by goal_completion node
    mock_ce.get_all_goals = Mock(return_value=[])
    mock_ce.ledger = Mock()
    mock_ce.ledger.entries = Mock(return_value=[])

    mock_step_planner = Mock()
    mock_step_planner.ingest_plan = Mock()
    mock_step_planner.record_step_outcomes = Mock()
    mock_step_planner.get_planning_context = Mock(return_value=Mock())
    mock_step_planner.determine_goal_completion_needs = Mock(return_value=False)
    mock_step_planner.determine_completion_strategy = Mock(
        return_value=CompletionStrategy.LEDGER_DIRECT
    )
    mock_step_planner.format_completion_dag_report = Mock(return_value="")

    mock_planning = Mock()
    mock_planning.step = mock_step_planner
    mock_ce.planning = mock_planning

    mock_ce._semantic = Mock()

    return mock_ce


def _make_mock_state_manager() -> tuple[Mock, Mock, Mock]:
    """Create mock state manager, checkpoint, and goal record."""
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

    return mock_sm, mock_ckpt, mock_gr


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

    mock_sm, _mock_ckpt, _mock_gr = _make_mock_state_manager()
    mock_anchor_mgr = Mock()
    mock_anchor_mgr.capture_iteration_start_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()
    mock_ce = _make_mock_ce()

    with (
        patch(
            "soothe.foundation.sloop.engine.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.foundation.context.engine.ContextEngine",
            return_value=mock_ce,
        ),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
    ):
        am_cls.create = AsyncMock(return_value=mock_anchor_mgr)
        loop = StrangeLoop(mock_core, AsyncMock(), SootheConfig())
        # IG-476: Mock generate_from_assessment to return done status directly
        loop.plan_phase.generate_from_assessment = AsyncMock(return_value=_make_done_plan_result())

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
    from soothe.foundation.sloop.engine.synthesis import SynthesisGenerator

    calls = 0

    async def counting_astream(*args, **kwargs):  # noqa: ARG002
        nonlocal calls
        calls += 1
        if False:
            yield None

    # Empty async generator for synthesis mock (never yields)
    async def empty_gen(*args, **kwargs):  # noqa: ARG002
        if False:
            yield None

    mock_core = _make_mock_core_with_checkpointer()
    mock_core.astream = counting_astream

    mock_sm, _mock_ckpt, _mock_gr = _make_mock_state_manager()
    mock_anchor_mgr = Mock()
    mock_anchor_mgr.capture_iteration_start_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()
    mock_ce = _make_mock_ce()
    # Add ledger content so LEDGER_DIRECT has content and doesn't fall back to synthesis
    from soothe.foundation.sloop.utils.messages import LoopAIMessage

    mock_ce.ledger.record_message = Mock()
    mock_ce.ledger.entries = Mock(
        return_value=[(LoopAIMessage(content="done content", phase="execute_step"), "execute_step")]
    )

    with (
        patch(
            "soothe.foundation.sloop.engine.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.foundation.context.engine.ContextEngine",
            return_value=mock_ce,
        ),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
        patch.object(
            SynthesisGenerator,
            "generate_synthesis",
            side_effect=empty_gen,
        ),
    ):
        am_cls.create = AsyncMock(return_value=mock_anchor_mgr)
        loop = StrangeLoop(mock_core, AsyncMock(), SootheConfig())
        loop._fast_llm = None  # Prevent synthesis LLM calls
        # IG-476: Mock generate_from_assessment to return done status directly
        loop.plan_phase.generate_from_assessment = AsyncMock(return_value=_make_done_plan_result())

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
    from soothe.foundation.sloop.engine.synthesis import SynthesisGenerator

    async def empty_gen(*args, **kwargs):  # noqa: ARG002
        if False:
            yield None

    mock_core = _make_mock_core_with_checkpointer()
    mock_core.astream = AsyncMock()

    mock_sm, _mock_ckpt, _mock_gr = _make_mock_state_manager()
    mock_anchor_mgr = Mock()
    mock_anchor_mgr.capture_iteration_start_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()
    mock_ce = _make_mock_ce()

    with (
        patch(
            "soothe.foundation.sloop.engine.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.foundation.context.engine.ContextEngine",
            return_value=mock_ce,
        ),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
        patch.object(
            SynthesisGenerator,
            "generate_synthesis",
            side_effect=empty_gen,
        ),
    ):
        am_cls.create = AsyncMock(return_value=mock_anchor_mgr)
        loop = StrangeLoop(mock_core, AsyncMock(), SootheConfig())
        loop._fast_llm = None  # Prevent synthesis LLM calls
        # IG-476: Mock generate_from_assessment to return done status directly
        loop.plan_phase.generate_from_assessment = AsyncMock(return_value=_make_done_plan_result())

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
    """RFC-223: StrangeLoop main thread id must align to loop_id."""
    mock_core = _make_mock_core_with_checkpointer()
    mock_core.astream = AsyncMock()

    mock_sm, mock_ckpt, _mock_gr = _make_mock_state_manager()
    mock_ckpt.status = "idle"
    mock_ckpt.current_thread_id = "legacy-thread"
    mock_ckpt.thread_ids = ["legacy-thread"]

    mock_anchor_mgr = Mock()
    mock_anchor_mgr.capture_iteration_start_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()
    mock_ce = _make_mock_ce()

    with (
        patch(
            "soothe.foundation.sloop.engine.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.foundation.context.engine.ContextEngine",
            return_value=mock_ce,
        ),
        patch(
            "soothe.foundation.sloop.engine.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
    ):
        am_cls.create = AsyncMock(return_value=mock_anchor_mgr)
        loop = StrangeLoop(mock_core, AsyncMock(), SootheConfig())
        # IG-476: Mock generate_from_assessment to return done status directly
        loop.plan_phase.generate_from_assessment = AsyncMock(return_value=_make_done_plan_result())

        _ = [
            evt
            async for evt in loop.run_with_progress(
                goal="simple goal",
                thread_id="thread-a",
                max_iterations=8,
            )
        ]

    mock_sm.initialize.assert_awaited_once_with("loop-test", 8)
