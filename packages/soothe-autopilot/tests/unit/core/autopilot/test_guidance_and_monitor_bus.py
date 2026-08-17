"""Unit tests for RFC-228 guidance absorption + dispatch injection (IG-678 P0)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe.config import SootheConfig
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus
from soothe.events.internal_events import (
    INTERNAL_GOAL_COMPLETED,
    INTERNAL_GOAL_FAILED,
    InternalGoalCompletedEvent,
    InternalGoalFailedEvent,
)

from soothe_autopilot.intake import absorb_user_guidance
from soothe_autopilot.service import AutopilotService

from .fakes import IdleFakeFactory


@pytest.mark.asyncio
async def test_absorb_guidance_async_on_real_ce() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("Ship OAuth")
    ok = await ce.absorb_guidance(goal.id, "Prefer PKCE", scope="goal", source="user")
    assert ok is True
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    assert refreshed.guidance_accumulated[-1]["text"] == "Prefer PKCE"
    assert refreshed.guidance_accumulated[-1]["source"] == "user"


@pytest.mark.asyncio
async def test_absorb_guidance_missing_goal() -> None:
    ce = ContextEngine()
    assert await ce.absorb_guidance("deadbeef", "nope") is False


@pytest.mark.asyncio
async def test_build_merged_context_attaches_guidance() -> None:
    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=1),
        internal_bus=bus,
        runner_factory=IdleFakeFactory(),
    )
    goal = await ce.create_goal("Add tests")
    await absorb_user_guidance(ce, goal.id, "Cover edge cases")
    bundle = await svc._build_merged_context(goal)
    assert "Cover edge cases" in bundle.operator_guidance


def _make_monitor(ce: ContextEngine, bus: InternalEventBus):
    from soothe_autopilot.monitor import AutopilotMonitor

    config = SootheConfig()
    with patch.object(SootheConfig, "create_chat_model", return_value=MagicMock()):
        return AutopilotMonitor(ce=ce, bus=bus, config=config)


@pytest.mark.asyncio
async def test_monitor_receives_internal_goal_completed() -> None:
    bus = InternalEventBus()
    ce = ContextEngine()
    monitor = _make_monitor(ce, bus)

    called: list[str] = []

    async def _capture_post(goal_id: str) -> None:
        called.append(goal_id)

    monitor._verify_post_completion = _capture_post  # type: ignore[method-assign]
    goal = await ce.create_goal("done goal")
    await ce.complete_goal(goal.id)

    assert bus.subscriber_count(INTERNAL_GOAL_COMPLETED) >= 1
    await bus.emit(InternalGoalCompletedEvent(goal_id=goal.id, loop_id="loop-1", plan_result={}))
    assert called == [goal.id]


@pytest.mark.asyncio
async def test_monitor_receives_internal_goal_failed() -> None:
    bus = InternalEventBus()
    ce = ContextEngine()
    monitor = _make_monitor(ce, bus)

    # Backoff reasoning now requires a bound ContextProjector
    # (RFC-222 §Goal-Report-Pair). Bind a fake so the monitor proceeds.
    fake_proj = MagicMock()
    fake_proj.build_preamble_text = AsyncMock(return_value="")
    monitor.bind_context_projector(fake_proj)

    goal = await ce.create_goal("fail goal")
    await ce.fail_goal(goal.id, error="boom")

    backoff_calls: list[str] = []

    async def fake_apply(decision: object, *, failed_goal_id: str = "") -> None:
        backoff_calls.append(failed_goal_id or "applied")

    async def fake_reason(*_a: object, **_k: object) -> object:
        class _D:
            backoff_to_goal_id = None
            reason = "retry parent"

        return _D()

    monitor._backoff_reasoner.reason_backoff = fake_reason  # type: ignore[method-assign]
    monitor._apply_backoff_decision = fake_apply  # type: ignore[method-assign]

    assert bus.subscriber_count(INTERNAL_GOAL_FAILED) >= 1
    await bus.emit(
        InternalGoalFailedEvent(
            goal_id=goal.id,
            loop_id="loop-1",
            evidence={
                "structured": {"outcome": "failed"},
                "narrative": "boom",
                "source": "layer2_execute",
            },
            error_message="boom",
        )
    )
    assert backoff_calls == [goal.id]
