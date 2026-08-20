"""StrangeLoop auto final response wiring."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.config import SootheConfig
from soothe.context.planning_models import CompletionStrategy
from soothe.sloop import StrangeLoop
from soothe.sloop.state.schemas import PlanResult


def _make_mock_core_with_checkpointer() -> Mock:
    """Create mock CoreAgent with graph.checkpointer as AsyncMock returning None.

    Without this, iteration-end anchor capture and context-window estimation
    try to await checkpointer.aget_tuple(config), causing TypeError on regular Mock.
    """
    mock_core = Mock()
    mock_graph = Mock()
    mock_graph.checkpointer = AsyncMock(return_value=None)
    mock_core.graph = mock_graph
    mock_core.aget_state = AsyncMock(return_value=Mock(tasks=[], values={}, next=()))

    async def _execution_astream(*args, **kwargs):  # noqa: ARG002
        yield {"messages": [{"content": "done content"}]}

    mock_core.execution_astream = _execution_astream
    return mock_core


def _make_done_plan_result() -> PlanResult:
    """Create a done PlanResult for tests."""
    return PlanResult(
        status="done",
        goal_progress="complete",
        plan_action="keep",
        decision=None,
        next_action="Goal achieved successfully",
        require_goal_completion=False,
        assessment_reasoning="",
    )


def _make_mock_ce(*, ledger_entries: list | None = None) -> Mock:
    """Build a mock ContextEngine with all required attributes.

    Args:
        ledger_entries: Optional CE ledger entries. When omitted, seeds one
            execute-step AI turn so LEDGER_DIRECT does not fall back to
            synthesis (which would call ``llm.astream`` on the AsyncMock planner).
            Pass ``[]`` for tests that need an empty ledger.
    """
    from soothe.context.models import StepDAG, StepNode

    mock_ce = Mock()
    mock_goal = Mock()
    mock_goal.id = "test-goal-id"
    # Real StepDAG so DISPATCH / RECONCILE / ROOT_EVAL can claim and green-check.
    mock_goal.steps = StepDAG(
        nodes={
            "ROOT": StepNode(id="ROOT", description="simple goal", status="pending"),
        }
    )
    mock_ce.load = AsyncMock(return_value=False)
    mock_ce.create_goal = AsyncMock(return_value=mock_goal)
    mock_ce.activate_goal = AsyncMock()
    mock_ce.save = AsyncMock()
    mock_ce.complete_goal = AsyncMock()
    mock_ce.finalize_goal = AsyncMock()  # Called by goal_completion node
    mock_ce.get_all_goals = Mock(return_value=[])
    mock_ce.get_goal = AsyncMock(return_value=mock_goal)

    async def _add_step(goal_id: str, step: StepNode) -> None:
        mock_goal.steps.add_step(step)

    async def _activate(goal_id: str, step_id: str) -> None:
        mock_goal.steps.mark_active(step_id)

    async def _complete(goal_id: str, step_id: str, execution: object) -> None:
        mock_goal.steps.mark_completed(step_id, execution)  # type: ignore[arg-type]

    async def _fail(goal_id: str, step_id: str, execution: object) -> None:
        mock_goal.steps.mark_failed(step_id, execution)  # type: ignore[arg-type]

    mock_ce.add_step = AsyncMock(side_effect=_add_step)
    mock_ce.activate_step = AsyncMock(side_effect=_activate)
    mock_ce.complete_step = AsyncMock(side_effect=_complete)
    mock_ce.fail_step = AsyncMock(side_effect=_fail)
    mock_ce.increment_iteration = Mock()
    mock_ce.defer_save = Mock()
    mock_ce.set_previous_plan = Mock()
    mock_ce.record_action = Mock()
    mock_ce.ledger = Mock()
    mock_ce.ledger.record_message = Mock()
    if ledger_entries is None:
        from soothe.sloop.utils.messages import LoopAIMessage

        ledger_entries = [
            (LoopAIMessage(content="done content", phase="execute_step"), "execute_step")
        ]
    mock_ce.ledger.entries = Mock(return_value=ledger_entries)
    mock_ce.get_ledger_entries = Mock(return_value=ledger_entries)

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
    mock_anchor_mgr.capture_iteration_end_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()
    mock_ce = _make_mock_ce()

    with (
        patch(
            "soothe.sloop.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.context.engine.ContextEngine",
            return_value=mock_ce,
        ),
        patch(
            "soothe.sloop.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
    ):
        am_cls.create = AsyncMock(return_value=mock_anchor_mgr)
        loop = StrangeLoop(mock_core, SootheConfig())

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
    from soothe.sloop.engine.synthesis import SynthesisGenerator

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
    mock_anchor_mgr.capture_iteration_end_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()
    mock_ce = _make_mock_ce()

    with (
        patch(
            "soothe.sloop.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.context.engine.ContextEngine",
            return_value=mock_ce,
        ),
        patch(
            "soothe.sloop.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
        patch.object(
            SynthesisGenerator,
            "generate_synthesis",
            side_effect=empty_gen,
        ),
    ):
        am_cls.create = AsyncMock(return_value=mock_anchor_mgr)
        loop = StrangeLoop(mock_core, SootheConfig())
        loop._fast_llm = None  # Prevent synthesis LLM calls

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
    from soothe.sloop.engine.synthesis import SynthesisGenerator

    async def empty_gen(*args, **kwargs):  # noqa: ARG002
        if False:
            yield None

    mock_core = _make_mock_core_with_checkpointer()
    mock_core.astream = AsyncMock()

    mock_sm, _mock_ckpt, _mock_gr = _make_mock_state_manager()
    mock_anchor_mgr = Mock()
    mock_anchor_mgr.capture_iteration_end_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()
    mock_ce = _make_mock_ce(ledger_entries=[])

    with (
        patch(
            "soothe.sloop.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.context.engine.ContextEngine",
            return_value=mock_ce,
        ),
        patch(
            "soothe.sloop.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
        patch.object(
            SynthesisGenerator,
            "generate_synthesis",
            side_effect=empty_gen,
        ),
    ):
        am_cls.create = AsyncMock(return_value=mock_anchor_mgr)
        loop = StrangeLoop(mock_core, SootheConfig())
        loop._fast_llm = None  # Prevent synthesis LLM calls

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
    mock_anchor_mgr.capture_iteration_end_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()
    mock_ce = _make_mock_ce()

    with (
        patch(
            "soothe.sloop.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.context.engine.ContextEngine",
            return_value=mock_ce,
        ),
        patch(
            "soothe.sloop.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
    ):
        am_cls.create = AsyncMock(return_value=mock_anchor_mgr)
        loop = StrangeLoop(mock_core, SootheConfig())

        _ = [
            evt
            async for evt in loop.run_with_progress(
                goal="simple goal",
                thread_id="thread-a",
                max_iterations=8,
            )
        ]

    mock_sm.initialize.assert_awaited_once_with("loop-test", 8)
