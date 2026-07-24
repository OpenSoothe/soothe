"""``StrangeLoop.run_with_progress`` forwards ``clarification_policy`` (IG-462)."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.config import SootheConfig
from soothe.sloop import StrangeLoop
from soothe.sloop.state.schemas import PlanResult


def _make_mock_core_with_checkpointer() -> Mock:
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


def _wire_mocks() -> tuple[Mock, Mock, Mock, Mock]:
    """Common mock harness shared by tests below."""
    mock_gr = Mock()
    mock_gr.loop_messages = []
    mock_ckpt = Mock()
    mock_ckpt.goal_history = []
    mock_ckpt.loop_messages = []

    mock_sm = Mock()
    mock_sm.loop_id = "loop-clarif"
    mock_sm.load = AsyncMock(return_value=None)
    mock_sm.initialize = AsyncMock(return_value=mock_ckpt)
    mock_sm.start_new_goal = Mock(return_value=mock_gr)
    mock_sm.save = AsyncMock()
    mock_sm.record_iteration = AsyncMock()
    mock_sm.finalize_goal = AsyncMock()
    mock_sm.close = AsyncMock()

    mock_gcm = Mock()

    mock_anchor_mgr = Mock()
    mock_anchor_mgr.capture_iteration_start_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()

    return mock_sm, mock_ckpt, mock_gcm, mock_anchor_mgr


def _make_mock_ce() -> Mock:
    """Build a mock ContextEngine with all required attributes."""
    from soothe.context.planning_models import CompletionStrategy
    from soothe.sloop.utils.messages import LoopAIMessage

    mock_ce = Mock()
    mock_goal = Mock()
    mock_goal.id = "test-goal-id"
    mock_ce.create_goal = AsyncMock(return_value=mock_goal)
    mock_ce.activate_goal = AsyncMock()
    mock_ce.save = AsyncMock()
    mock_ce.load = AsyncMock(return_value=False)
    mock_ce.complete_goal = AsyncMock()
    mock_ce.get_all_goals = Mock(return_value=[])
    mock_ce.ledger = Mock()
    # Seed execute-step content so LEDGER_DIRECT does not fall back to synthesis.
    mock_ce.ledger.record_message = Mock()
    mock_ce.ledger.entries = Mock(
        return_value=[(LoopAIMessage(content="done content", phase="execute_step"), "execute_step")]
    )

    # Mock planning subengine
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

    # Mock semantic loader
    mock_ce._semantic = Mock()

    return mock_ce


@pytest.mark.asyncio
async def test_run_with_progress_forwards_clarification_policy() -> None:
    """The policy passed to ``run_with_progress`` must reach LoopRuntimeContext."""
    sentinel_policy = object()
    captured: dict[str, object | None] = {}

    real_runtime_context_cls: type

    def _capturing_runtime_context(*args, **kwargs):
        captured["clarification_policy"] = kwargs.get("clarification_policy")
        return real_runtime_context_cls(*args, **kwargs)

    from soothe.sloop.orchestrator import runtime_context as rtx_mod

    real_runtime_context_cls = rtx_mod.LoopRuntimeContext

    mock_core = _make_mock_core_with_checkpointer()

    async def noop_astream(*_args, **_kwargs):
        if False:
            yield None

    mock_core.astream = noop_astream

    mock_sm, _ckpt, mock_gcm, mock_anchor_mgr = _wire_mocks()
    mock_ce = _make_mock_ce()

    with (
        patch(
            "soothe.sloop.engine.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.context.engine.ContextEngine",
            return_value=mock_ce,
        ),
        patch(
            "soothe.sloop.engine.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
        patch(
            "soothe.sloop.engine.strange_loop.LoopRuntimeContext",
            side_effect=_capturing_runtime_context,
        ),
    ):
        am_cls.create = AsyncMock(return_value=mock_anchor_mgr)
        loop = StrangeLoop(mock_core, AsyncMock(), SootheConfig())
        # IG-476: Mock generate_from_assessment to return done status directly
        loop.plan_phase.generate_from_assessment = AsyncMock(return_value=_make_done_plan_result())

        _ = [
            evt
            async for evt in loop.run_with_progress(
                goal="g", thread_id="t", clarification_policy=sentinel_policy
            )
        ]

    assert captured["clarification_policy"] is sentinel_policy


@pytest.mark.asyncio
async def test_run_with_progress_defaults_clarification_policy_to_none() -> None:
    """Omitting the kwarg keeps the legacy ``None`` default."""
    captured: dict[str, object | None] = {}

    real_runtime_context_cls: type

    def _capturing_runtime_context(*args, **kwargs):
        captured["clarification_policy"] = kwargs.get("clarification_policy")
        return real_runtime_context_cls(*args, **kwargs)

    from soothe.sloop.orchestrator import runtime_context as rtx_mod

    real_runtime_context_cls = rtx_mod.LoopRuntimeContext

    mock_core = _make_mock_core_with_checkpointer()

    async def noop_astream(*_args, **_kwargs):
        if False:
            yield None

    mock_core.astream = noop_astream

    mock_sm, _ckpt, mock_gcm, mock_anchor_mgr = _wire_mocks()
    mock_ce = _make_mock_ce()

    with (
        patch(
            "soothe.sloop.engine.strange_loop.StrangeLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.context.engine.ContextEngine",
            return_value=mock_ce,
        ),
        patch(
            "soothe.sloop.engine.strange_loop.CheckpointAnchorManager",
        ) as am_cls,
        patch(
            "soothe.sloop.engine.strange_loop.LoopRuntimeContext",
            side_effect=_capturing_runtime_context,
        ),
    ):
        am_cls.create = AsyncMock(return_value=mock_anchor_mgr)
        loop = StrangeLoop(mock_core, AsyncMock(), SootheConfig())
        # IG-476: Mock generate_from_assessment to return done status directly
        loop.plan_phase.generate_from_assessment = AsyncMock(return_value=_make_done_plan_result())

        _ = [
            evt
            async for evt in loop.run_with_progress(
                goal="g",
                thread_id="t",
            )
        ]

    assert captured["clarification_policy"] is None
