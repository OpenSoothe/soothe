"""``AgentLoop.run_with_progress`` forwards ``clarification_policy`` (IG-462)."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.config import SootheConfig
from soothe.core.loop import AgentLoop
from soothe.core.loop.state.schemas import StatusAssessment


def _make_mock_core_with_checkpointer() -> Mock:
    mock_core = Mock()
    mock_graph = Mock()
    mock_graph.checkpointer = AsyncMock(return_value=None)
    mock_core.graph = mock_graph
    return mock_core


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
    mock_gcm.get_plan_context = AsyncMock(return_value=[])

    mock_anchor_mgr = Mock()
    mock_anchor_mgr.capture_iteration_start_anchor = AsyncMock()
    mock_anchor_mgr.close = AsyncMock()

    return mock_sm, mock_ckpt, mock_gcm, mock_anchor_mgr


@pytest.mark.asyncio
async def test_run_with_progress_forwards_clarification_policy() -> None:
    """The policy passed to ``run_with_progress`` must reach LoopRuntimeContext."""
    sentinel_policy = object()
    captured: dict[str, object | None] = {}

    real_runtime_context_cls: type

    def _capturing_runtime_context(*args, **kwargs):
        captured["clarification_policy"] = kwargs.get("clarification_policy")
        return real_runtime_context_cls(*args, **kwargs)

    from soothe.core.loop.orchestrator import runtime_context as rtx_mod

    real_runtime_context_cls = rtx_mod.LoopRuntimeContext

    mock_core = _make_mock_core_with_checkpointer()

    async def noop_astream(*_args, **_kwargs):
        if False:
            yield None

    mock_core.astream = noop_astream

    mock_sm, _ckpt, mock_gcm, mock_anchor_mgr = _wire_mocks()

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
        patch(
            "soothe.core.loop.engine.agent_loop.LoopRuntimeContext",
            side_effect=_capturing_runtime_context,
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

    from soothe.core.loop.orchestrator import runtime_context as rtx_mod

    real_runtime_context_cls = rtx_mod.LoopRuntimeContext

    mock_core = _make_mock_core_with_checkpointer()

    async def noop_astream(*_args, **_kwargs):
        if False:
            yield None

    mock_core.astream = noop_astream

    mock_sm, _ckpt, mock_gcm, mock_anchor_mgr = _wire_mocks()

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
        patch(
            "soothe.core.loop.engine.agent_loop.LoopRuntimeContext",
            side_effect=_capturing_runtime_context,
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
                goal="g",
                thread_id="t",
            )
        ]

    assert captured["clarification_policy"] is None
