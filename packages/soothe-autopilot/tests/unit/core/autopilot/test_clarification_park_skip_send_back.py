"""IG-749: Autopilot skips send_back when goal is parked awaiting clarification."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_autopilot.service import AutopilotService


@pytest.mark.asyncio
async def test_needs_replan_skips_send_back_when_awaiting_clarification() -> None:
    svc = AutopilotService.__new__(AutopilotService)
    svc._context_store = None
    svc._goal_loop_token_cursor = {}
    svc._dispatch_tasks = {}
    svc._ce = MagicMock()
    parked = SimpleNamespace(status="awaiting_clarification")
    svc._ce.get_goal_sync = MagicMock(return_value=parked)
    svc._ce.get_goal = AsyncMock(return_value=parked)
    svc._mirror_contribution_steps = AsyncMock()
    svc._commit_loop_end_report = AsyncMock()
    svc._apply_send_back_or_fail = AsyncMock()
    svc._release_goal_runtime = AsyncMock()
    svc._persist_goals = AsyncMock()

    async def _run(_request):  # noqa: ANN001
        yield (
            (),
            "custom",
            {
                "type": "soothe.internal.autopilot.goal_completion",
                "goal_id": "g1",
                "outcome": "needs_replan",
                "context_contribution": {},
                "evidence_summary": "clarification deferred",
            },
        )

    worker = SimpleNamespace(loop_id="loop-1", runner=SimpleNamespace(run=_run))
    request = SimpleNamespace()

    await AutopilotService._consume_worker_stream(svc, "g1", worker, request)

    svc._commit_loop_end_report.assert_awaited_once()
    svc._apply_send_back_or_fail.assert_not_awaited()


@pytest.mark.asyncio
async def test_needs_replan_send_back_when_not_parked() -> None:
    svc = AutopilotService.__new__(AutopilotService)
    svc._context_store = None
    svc._goal_loop_token_cursor = {}
    svc._dispatch_tasks = {}
    svc._ce = MagicMock()
    active = SimpleNamespace(status="active")
    svc._ce.get_goal_sync = MagicMock(return_value=active)
    svc._ce.get_goal = AsyncMock(return_value=active)
    svc._mirror_contribution_steps = AsyncMock()
    svc._commit_loop_end_report = AsyncMock()
    svc._apply_send_back_or_fail = AsyncMock()
    svc._release_goal_runtime = AsyncMock()
    svc._persist_goals = AsyncMock()

    async def _run(_request):  # noqa: ANN001
        yield (
            (),
            "custom",
            {
                "type": "soothe.internal.autopilot.goal_completion",
                "goal_id": "g1",
                "outcome": "needs_replan",
                "context_contribution": {},
                "evidence_summary": "insufficient evidence",
            },
        )

    worker = SimpleNamespace(loop_id="loop-1", runner=SimpleNamespace(run=_run))
    request = SimpleNamespace()

    await AutopilotService._consume_worker_stream(svc, "g1", worker, request)

    svc._apply_send_back_or_fail.assert_awaited_once()
