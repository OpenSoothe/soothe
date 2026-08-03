"""Unit tests for RFC-228 guidance absorption + dispatch injection (IG-678 P0)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from soothe.autopilot.service import AutopilotService, _collect_operator_guidance
from soothe.config import SootheConfig
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.context.models import GoalNode
from soothe.events.internal_bus import InternalEventBus
from soothe.events.internal_events import (
    INTERNAL_GOAL_COMPLETED,
    INTERNAL_GOAL_FAILED,
    InternalGoalCompletedEvent,
    InternalGoalFailedEvent,
)

from .fakes import IdleFakeFactory


@pytest.mark.asyncio
async def test_absorb_guidance_async_on_real_ce() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("Ship OAuth")
    ok = await ce.absorb_guidance(goal.id, "Prefer PKCE", scope="goal")
    assert ok is True
    refreshed = await ce.get_goal(goal.id)
    assert refreshed is not None
    assert refreshed.guidance_accumulated[-1]["text"] == "Prefer PKCE"


@pytest.mark.asyncio
async def test_absorb_guidance_missing_goal() -> None:
    ce = ContextEngine()
    assert await ce.absorb_guidance("deadbeef", "nope") is False


def test_collect_operator_guidance_includes_goal_and_job_scope() -> None:
    root = GoalNode(id="root0001", description="job root")
    root.guidance_accumulated = [
        {"text": "job-wide: use feature branch", "scope": "job"},
        {"text": "root-only note", "scope": "goal"},
    ]
    child = GoalNode(id="child001", description="implement", parent_id="root0001")
    child.guidance_accumulated = [{"text": "focus on login route", "scope": "goal"}]
    goals = {"root0001": root, "child001": child}

    texts = _collect_operator_guidance(child, goals)
    assert "focus on login route" in texts
    assert "job-wide: use feature branch" in texts
    assert "root-only note" not in texts


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
    await ce.absorb_guidance(goal.id, "Cover edge cases")
    bundle = await svc._build_merged_context(goal)
    assert "Cover edge cases" in bundle.operator_guidance


def _make_monitor(ce: ContextEngine, bus: InternalEventBus):
    from soothe.autopilot.monitor import AutopilotMonitor

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
