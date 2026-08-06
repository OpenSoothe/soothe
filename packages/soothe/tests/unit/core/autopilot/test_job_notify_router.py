"""IG-713: job lifecycle NotificationRouter + dedup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from soothe.autopilot.notify import NotificationRouter, NotifyIntent
from soothe.config.models import AutopilotNotifyConfig, NotifyEventsConfig, NotifyTargetConfig
from soothe.context.models import GoalNode


def _notify_cfg(**kwargs: object) -> AutopilotNotifyConfig:
    base = AutopilotNotifyConfig(
        enabled=True,
        suspend_after_seconds=2700,
        events=NotifyEventsConfig(),
        targets=[NotifyTargetConfig(kind="email", to_address="ops@example.com")],
    )
    return base.model_copy(update=kwargs)


@pytest.mark.asyncio
async def test_router_emits_job_completed_for_root() -> None:
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    root = GoalNode(id="jobroot01", description="Ship feature", status="completed")
    progress = {
        "total_goals": 3,
        "completed_goals": 3,
        "failed_goals": 0,
        "active_goals": 0,
        "pending_goals": 0,
        "suspended_goals": 0,
        "cancelled_goals": 0,
        "pct_complete": 100,
        "highlights": [],
        "highlights_omitted": 0,
    }
    intent = await router.on_job_root_status(root, progress=progress)
    assert intent is not None
    assert intent.kind == "job.completed"
    assert intent.progress is not None
    assert intent.progress["total_goals"] == 3
    assert "(3/3)" in intent.title
    assert "Progress: 3/3 goals" in intent.body
    assert seen and seen[0].job_id == "jobroot01"


@pytest.mark.asyncio
async def test_router_ignores_child_goals() -> None:
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    child = GoalNode(
        id="child001",
        description="maker",
        status="completed",
        parent_id="jobroot01",
    )
    assert await router.on_job_root_status(child) is None
    assert not seen


@pytest.mark.asyncio
async def test_router_dedup_same_intent() -> None:
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    root = GoalNode(id="jobroot02", description="x", status="failed", error="boom")
    assert await router.on_job_root_status(root) is not None
    assert await router.on_job_root_status(root) is None
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_suspend_timeout_scan() -> None:
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(
        _notify_cfg(suspend_after_seconds=60),
        dispatch_fn=_dispatch,
    )
    now = datetime.now(UTC)
    root = GoalNode(
        id="jobroot03",
        description="paused",
        status="suspended",
        suspended_at=now - timedelta(minutes=45),
        updated_at=now - timedelta(minutes=45),
    )
    emitted = await router.scan_suspended_timeouts([root], now=now)
    assert len(emitted) == 1
    assert emitted[0].kind == "job.suspended_timeout"
    assert seen[0].suspended_for_seconds is not None
    assert seen[0].suspended_for_seconds >= 60


@pytest.mark.asyncio
async def test_router_disabled_noop() -> None:
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(enabled=False), dispatch_fn=_dispatch)
    root = GoalNode(id="jobroot04", description="x", status="completed")
    assert await router.on_job_root_status(root) is None
    assert not seen
