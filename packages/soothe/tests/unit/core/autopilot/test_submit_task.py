"""Tests for AutopilotService.submit_task / list_goals / get_goal / cancel_goal (RFC-222 revised, Phase C, RFC-625)."""

from __future__ import annotations

import pytest

from soothe.config.models import AutopilotConfig
from soothe.foundation.autopilot.service import AutopilotService
from soothe.foundation.context import ContextEngine
from soothe.foundation.events.internal_bus import InternalEventBus

from .fakes import IdleFakeFactory


def _service() -> AutopilotService:
    bus = InternalEventBus()
    ce = ContextEngine()
    return AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=2, max_parallel_goals=2),
        internal_bus=bus,
        runner_factory=IdleFakeFactory(),
    )


class TestSubmitTask:
    @pytest.mark.asyncio
    async def test_returns_goal_with_id(self) -> None:
        svc = _service()
        goal = await svc.submit_task("write a poem")
        assert goal.id
        assert goal.description == "write a poem"
        assert goal.status == "pending"
        assert goal.priority == 50

    @pytest.mark.asyncio
    async def test_priority_passed_through(self) -> None:
        svc = _service()
        goal = await svc.submit_task("urgent", priority=90)
        assert goal.priority == 90

    @pytest.mark.asyncio
    async def test_dependencies_passed_through(self) -> None:
        svc = _service()
        a = await svc.submit_task("a")
        b = await svc.submit_task("b", depends_on=[a.id])
        assert b.depends_on == [a.id]

    @pytest.mark.asyncio
    async def test_parent_id_validation(self) -> None:
        svc = _service()
        with pytest.raises(ValueError, match="not found"):
            await svc.submit_task("orphan", parent_id="ghost-id")

    @pytest.mark.asyncio
    async def test_workspace_stored_when_provided(self, tmp_path) -> None:
        svc = _service()
        goal = await svc.submit_task("list files", workspace=str(tmp_path))
        assert goal.workspace == str(tmp_path.resolve())

    @pytest.mark.asyncio
    async def test_workspace_none_when_omitted(self) -> None:
        svc = _service()
        goal = await svc.submit_task("no workspace")
        assert goal.workspace is None


class TestListAndGet:
    @pytest.mark.asyncio
    async def test_list_goals_returns_all_by_default(self) -> None:
        svc = _service()
        await svc.submit_task("a")
        await svc.submit_task("b")
        goals = await svc.list_goals()
        assert {g.description for g in goals} == {"a", "b"}

    @pytest.mark.asyncio
    async def test_list_goals_filters_by_status(self) -> None:
        svc = _service()
        await svc.submit_task("a")
        # peek_ready_goals returns candidates without activation
        ready = svc._ce.peek_ready_goals(limit=1)
        assert ready[0].status == "pending"  # Not activated by peek

        # claim_goal activates the goal
        claimed = svc._ce.claim_goal(ready[0].id, loop_id="test-loop")
        assert claimed is not None
        assert claimed.status == "active"

        active = await svc.list_goals(status="active")
        pending = await svc.list_goals(status="pending")
        assert len(active) == 1
        assert pending == []

    @pytest.mark.asyncio
    async def test_get_goal_returns_none_for_missing(self) -> None:
        svc = _service()
        assert await svc.get_goal("does-not-exist") is None

    @pytest.mark.asyncio
    async def test_get_goal_returns_goal(self) -> None:
        svc = _service()
        created = await svc.submit_task("findable")
        out = await svc.get_goal(created.id)
        assert out is not None
        assert out.id == created.id


class TestCancelGoal:
    @pytest.mark.asyncio
    async def test_cancel_existing_goal_marks_cancelled(self) -> None:
        svc = _service()
        goal = await svc.submit_task("doomed", max_retries=0)
        cancelled = await svc.cancel_goal(goal.id, reason="user said no")
        assert cancelled is not None
        assert cancelled.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_missing_goal_returns_none(self) -> None:
        svc = _service()
        assert await svc.cancel_goal("missing") is None
