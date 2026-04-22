"""Tests for merging LangGraph thread excerpts into AgentLoop Plan state (IG-198)."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from soothe.cognition.agent_loop import AgentLoop
from soothe.cognition.agent_loop.schemas import PlanResult
from soothe.config import SootheConfig


@pytest.mark.asyncio
async def test_run_with_progress_merges_runner_thread_excerpts_into_loop_state() -> None:
    """Runner-supplied prior turns must appear in ``LoopState.plan_conversation_excerpts``."""
    captured: dict[str, list[str]] = {}

    async def fake_plan(goal, state, context):  # noqa: ARG001
        captured["excerpts"] = list(state.plan_conversation_excerpts)
        return PlanResult(
            status="done",
            evidence_summary="",
            goal_progress=1.0,
            confidence=0.9,
            reasoning="",
            next_action="done",
            plan_action="new",
            full_output="final report body",
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
    mock_gcm.get_plan_context = AsyncMock(return_value=["<briefing>ctx</briefing>"])

    async def noop_astream(*args, **kwargs):  # noqa: ARG002
        if False:
            yield None

    mock_core = Mock()
    mock_core.astream = noop_astream

    runner_excerpts = [
        "<user>\nfirst ask\n</user>",
        "<assistant>\nTHE REPORT\n</assistant>",
    ]

    with (
        patch(
            "soothe.cognition.agent_loop.agent_loop.AgentLoopStateManager",
            return_value=mock_sm,
        ),
        patch(
            "soothe.cognition.agent_loop.agent_loop.GoalContextManager",
            return_value=mock_gcm,
        ),
    ):
        loop = AgentLoop(mock_core, AsyncMock(), SootheConfig())
        loop.plan_phase.plan = fake_plan

        events = [
            evt
            async for evt in loop.run_with_progress(
                goal="translate the report",
                thread_id="thread-a",
                plan_conversation_excerpts=runner_excerpts,
            )
        ]

    assert events, "expected at least one event from run_with_progress"
    merged = "\n".join(captured["excerpts"])
    assert "<briefing>ctx</briefing>" in merged
    assert "first ask" in merged
    assert "THE REPORT" in merged
