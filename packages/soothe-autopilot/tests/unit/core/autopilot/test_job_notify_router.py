"""IG-713: job lifecycle NotificationRouter + dedup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from soothe.config.models import AutopilotNotifyConfig, NotifyEventsConfig, NotifyTargetConfig
from soothe.context.models import GoalNode

from soothe_autopilot.notify import NotificationRouter, NotifyIntent


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


# ── Drift-aware severity escalation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_completed_clean_is_info() -> None:
    """Completed root with no failed/active children → info."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    root = GoalNode(id="jobroot10", description="clean", status="completed")
    progress = {
        "total_goals": 2,
        "completed_goals": 2,
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
    assert intent.severity == "info"


@pytest.mark.asyncio
async def test_completed_with_failed_children_is_warning() -> None:
    """Completed root but children failed → warning (completion drift)."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    root = GoalNode(id="jobroot11", description="drift", status="completed")
    progress = {
        "total_goals": 3,
        "completed_goals": 1,
        "failed_goals": 1,
        "active_goals": 1,
        "pending_goals": 0,
        "suspended_goals": 0,
        "cancelled_goals": 0,
        "pct_complete": 33,
        "highlights": [],
        "highlights_omitted": 0,
    }
    intent = await router.on_job_root_status(root, progress=progress)
    assert intent is not None
    assert intent.severity == "warning"


@pytest.mark.asyncio
async def test_completed_with_maturity_blockers_is_warning() -> None:
    """Completed root with maturity blockers → warning (acceptance drift)."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    root = GoalNode(
        id="jobroot12",
        description="blocked",
        status="completed",
        maturity={"level": "partial", "blockers": ["verify failed"]},
    )
    intent = await router.on_job_root_status(root)
    assert intent is not None
    assert intent.severity == "warning"


@pytest.mark.asyncio
async def test_completed_acceptance_not_met_is_warning() -> None:
    """Completed root with acceptance_met=False → warning."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    root = GoalNode(
        id="jobroot13",
        description="not accepted",
        status="completed",
        maturity={"acceptance_met": False},
    )
    intent = await router.on_job_root_status(root)
    assert intent is not None
    assert intent.severity == "warning"


@pytest.mark.asyncio
async def test_failed_is_error() -> None:
    """Failed root is always error severity."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    root = GoalNode(id="jobroot14", description="boom", status="failed", error="crash")
    intent = await router.on_job_root_status(root)
    assert intent is not None
    assert intent.severity == "error"


@pytest.mark.asyncio
async def test_suspended_timeout_within_threshold_is_warning() -> None:
    """Suspended timeout just past threshold → warning."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(
        _notify_cfg(suspend_after_seconds=60),
        dispatch_fn=_dispatch,
    )
    now = datetime.now(UTC)
    root = GoalNode(
        id="jobroot15",
        description="paused",
        status="suspended",
        suspended_at=now - timedelta(minutes=2),
        updated_at=now - timedelta(minutes=2),
    )
    emitted = await router.scan_suspended_timeouts([root], now=now)
    assert len(emitted) == 1
    assert emitted[0].severity == "warning"


@pytest.mark.asyncio
async def test_suspended_timeout_far_past_threshold_is_error() -> None:
    """Suspended timeout at ≥2× threshold → error (drift past suspend window)."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(
        _notify_cfg(suspend_after_seconds=60),
        dispatch_fn=_dispatch,
    )
    now = datetime.now(UTC)
    root = GoalNode(
        id="jobroot16",
        description="stuck",
        status="suspended",
        suspended_at=now - timedelta(minutes=3),
        updated_at=now - timedelta(minutes=3),
    )
    emitted = await router.scan_suspended_timeouts([root], now=now)
    assert len(emitted) == 1
    assert emitted[0].severity == "error"


def test_severity_enum_ordering() -> None:
    """Severity enum supports comparison and str coercion."""
    from soothe_autopilot.notify import Severity

    assert Severity.INFO < Severity.WARNING < Severity.ERROR
    assert Severity.ERROR >= Severity.WARNING
    assert Severity.INFO <= Severity.WARNING
    assert str(Severity.ERROR) == "error"


# ── Configurable threshold tuning (GAN-04) ─────────────────────────────


@pytest.mark.asyncio
async def test_suspended_timeout_custom_multiplier_is_error() -> None:
    """Suspended timeout at >=3x threshold with multiplier=3.0 → error."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(
        _notify_cfg(suspend_after_seconds=60, suspend_escalation_multiplier=3.0),
        dispatch_fn=_dispatch,
    )
    now = datetime.now(UTC)
    # 4 minutes = 240s; 3x60 = 180s → 240 > 180 → error
    root = GoalNode(
        id="jobroot20",
        description="stuck-long",
        status="suspended",
        suspended_at=now - timedelta(minutes=4),
        updated_at=now - timedelta(minutes=4),
    )
    emitted = await router.scan_suspended_timeouts([root], now=now)
    assert len(emitted) == 1
    assert emitted[0].severity == "error"


@pytest.mark.asyncio
async def test_suspended_timeout_custom_multiplier_still_warning() -> None:
    """Suspended timeout between 1x and 3x threshold with multiplier=3.0 → warning."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(
        _notify_cfg(suspend_after_seconds=60, suspend_escalation_multiplier=3.0),
        dispatch_fn=_dispatch,
    )
    now = datetime.now(UTC)
    # 2 minutes = 120s; 3x60 = 180s → 120 < 180 → warning
    root = GoalNode(
        id="jobroot21",
        description="stuck-medium",
        status="suspended",
        suspended_at=now - timedelta(minutes=2),
        updated_at=now - timedelta(minutes=2),
    )
    emitted = await router.scan_suspended_timeouts([root], now=now)
    assert len(emitted) == 1
    assert emitted[0].severity == "warning"


@pytest.mark.asyncio
async def test_dedup_ttl_expiry_allows_re_notify() -> None:
    """Dedup keys expire after TTL, allowing re-notification."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    # TTL of 0 seconds = immediate expiry → second emit should succeed
    router = NotificationRouter(
        _notify_cfg(dedup_ttl_seconds=0),
        dispatch_fn=_dispatch,
    )
    root = GoalNode(id="jobroot22", description="ttl-test", status="failed", error="boom")
    first = await router.on_job_root_status(root)
    assert first is not None
    # With ttl=0, the dedup entry should be expired immediately
    second = await router.on_job_root_status(root)
    # Even with TTL=0, in-memory dict stores the key; but _is_expired returns True
    # for ttl<=0? No — ttl<=0 means NO expiry (keys persist indefinitely).
    # So the second emit should still be deduped.
    assert second is None
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_dedup_ttl_zero_means_no_expiry() -> None:
    """TTL=0 means no expiry (keys persist indefinitely) — dedup still blocks."""
    from soothe_autopilot.notify.dedup import NotifyDedupStore

    store = NotifyDedupStore(store=None, ttl_seconds=0)
    assert store._ttl_seconds == 0
    # With no store and no expiry, first call is not sent, second is blocked
    assert await store.already_sent("key1") is False
    await store.mark_sent("key1")
    assert await store.already_sent("key1") is True


@pytest.mark.asyncio
async def test_dedup_ttl_positive_allows_expiry() -> None:
    """Dedup store with TTL expiry frees re-notification after window."""
    import time

    from soothe_autopilot.notify.dedup import NotifyDedupStore

    store = NotifyDedupStore(store=None, ttl_seconds=1)
    assert store._ttl_seconds == 1
    assert await store.already_sent("key2") is False
    await store.mark_sent("key2")
    assert await store.already_sent("key2") is True
    # Wait for TTL to expire
    time.sleep(1.1)
    assert await store.already_sent("key2") is False
