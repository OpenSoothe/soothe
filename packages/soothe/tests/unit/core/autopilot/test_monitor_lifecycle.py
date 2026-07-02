"""AutopilotService ↔ AutopilotMonitor lifecycle and intake routing (RFC-222 pilot)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.config.models import AutonomousConfig
from soothe.foundation.autopilot.monitor.models import GoalIntakeResult
from soothe.foundation.autopilot.service import AutopilotService
from soothe.foundation.context import ContextEngine
from soothe.foundation.events.internal_bus import InternalEventBus

from .fakes import IdleFakeFactory


def _service(*, monitor: MagicMock | None = None) -> AutopilotService:
    bus = InternalEventBus()
    ce = ContextEngine()
    return AutopilotService(
        ce=ce,
        config=AutonomousConfig(max_loops=2, max_parallel_goals=2),
        internal_bus=bus,
        monitor=monitor,
        runner_factory=IdleFakeFactory(),
    )


class TestMonitorLifecycle:
    @pytest.mark.asyncio
    async def test_start_stops_monitor_when_wired(self) -> None:
        monitor = MagicMock()
        monitor.start = AsyncMock()
        monitor.stop = AsyncMock()
        svc = _service(monitor=monitor)

        await svc.start()
        monitor.start.assert_awaited_once()
        assert svc._running is True

        await svc.stop()
        monitor.stop.assert_awaited_once()
        assert svc._running is False

    @pytest.mark.asyncio
    async def test_start_without_monitor(self) -> None:
        svc = _service(monitor=None)
        await svc.start()
        assert svc._running is True
        await svc.stop()
        assert svc._running is False


class TestSubmitTaskMonitorRouting:
    @pytest.mark.asyncio
    async def test_submit_routes_through_monitor_intake(self, tmp_path) -> None:
        monitor = MagicMock()
        monitor.start = AsyncMock()
        monitor.stop = AsyncMock()
        intake_result = GoalIntakeResult(status="accepted", goal_id="placeholder")
        monitor.intake_goal = AsyncMock(return_value=intake_result)
        svc = _service(monitor=monitor)
        ws = str(tmp_path)

        with patch.object(
            svc._ce,
            "get_goal",
            new=AsyncMock(
                return_value=MagicMock(
                    id="goal-abc",
                    description="ship feature",
                    status="pending",
                    priority=50,
                    workspace=ws,
                )
            ),
        ) as get_goal:
            goal = await svc.submit_task(
                "ship feature",
                priority=70,
                workspace=ws,
                parent_id="parent-1",
            )

        monitor.intake_goal.assert_awaited_once()
        kwargs = monitor.intake_goal.await_args.kwargs
        assert kwargs["priority"] == 70
        assert kwargs["workspace"] == ws
        assert kwargs["parent_id"] == "parent-1"
        get_goal.assert_awaited_once_with("placeholder")
        assert goal.id == "goal-abc"

    @pytest.mark.asyncio
    async def test_submit_rejects_failed_intake(self) -> None:
        monitor = MagicMock()
        monitor.intake_goal = AsyncMock(
            return_value=GoalIntakeResult(status="rejected", reason="duplicate goal")
        )
        svc = _service(monitor=monitor)

        with pytest.raises(ValueError, match="duplicate goal"):
            await svc.submit_task("dup")
