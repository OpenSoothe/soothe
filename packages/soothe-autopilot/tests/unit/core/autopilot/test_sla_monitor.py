"""SLA monitor — overdue gap detection and tiered escalation alerts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from soothe.config.models import (
    AutopilotNotifyConfig,
    NotifyEventsConfig,
    NotifyTargetConfig,
    SlaConfig,
)
from soothe.context.models import GoalNode

from soothe_autopilot.notify import NotificationRouter, NotifyIntent
from soothe_autopilot.sla import SlaMonitor, SlaTier


def _sla_cfg(**kwargs: object) -> SlaConfig:
    base = SlaConfig(
        enabled=True,
        warning_seconds=3600,
        critical_seconds=7200,
        breach_seconds=14400,
    )
    return base.model_copy(update=kwargs)


def _notify_cfg(sla: SlaConfig | None = None, **kwargs: object) -> AutopilotNotifyConfig:
    return AutopilotNotifyConfig(
        enabled=True,
        events=NotifyEventsConfig(),
        targets=[NotifyTargetConfig(kind="email", to_address="ops@example.com")],
        sla=sla or _sla_cfg(),
    ).model_copy(update=kwargs)


def _goal(
    *,
    id: str = "goal0001",
    description: str = "Ship feature X",
    status: str = "active",
    started_at: datetime | None = None,
    last_gap_analysis: dict | None = None,
    parent_id: str | None = None,
) -> GoalNode:
    return GoalNode(
        id=id,
        description=description,
        status=status,
        started_at=started_at,
        last_gap_analysis=last_gap_analysis,
        parent_id=parent_id,
    )


def _gap_analysis(
    *,
    remaining_gaps: list[str] | None = None,
    distance: str = "moderate",
    components: list[dict] | None = None,
) -> dict:
    if remaining_gaps is None:
        remaining_gaps = ["API not implemented", "Tests missing"]
    if components is None:
        components = [
            {"component": "API", "status": "partial"},
            {"component": "Tests", "status": "not_started"},
        ]
    return {
        "remaining_gaps": remaining_gaps,
        "distance_from_goal": distance,
        "components": components,
    }


# ── SlaTier ordering ─────────────────────────────────────────────────────


def test_tier_ordering() -> None:
    assert SlaTier.WARNING < SlaTier.CRITICAL
    assert SlaTier.CRITICAL < SlaTier.BREACH
    assert SlaTier.BREACH > SlaTier.WARNING
    assert SlaTier.CRITICAL >= SlaTier.CRITICAL


# ── SlaConfig validation ─────────────────────────────────────────────────


def test_sla_config_rejects_critical_below_warning() -> None:
    with pytest.raises(ValueError, match="critical_seconds"):
        SlaConfig(enabled=True, warning_seconds=3600, critical_seconds=1800)


def test_sla_config_rejects_breach_below_critical() -> None:
    with pytest.raises(ValueError, match="breach_seconds"):
        SlaConfig(enabled=True, critical_seconds=7200, breach_seconds=3600)


def test_sla_config_allows_zero_thresholds() -> None:
    """Zero thresholds disable a tier — should not raise."""
    cfg = SlaConfig(enabled=True, warning_seconds=0, critical_seconds=0, breach_seconds=0)
    assert cfg.warning_seconds == 0


# ── SlaMonitor.scan ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_no_gaps_no_breach() -> None:
    """Goal with no gap analysis → not overdue."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(), router)
    now = datetime.now(UTC)
    goal = _goal(started_at=now - timedelta(hours=5))
    result = await monitor.scan([goal], now=now)
    assert result.breaches == []
    assert result.emitted_intents == 0
    assert not seen


@pytest.mark.asyncio
async def test_scan_disabled_returns_empty() -> None:
    """SLA monitor disabled → no scan."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(sla=_sla_cfg(enabled=False)), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(enabled=False), router)
    now = datetime.now(UTC)
    goal = _goal(
        started_at=now - timedelta(hours=5),
        last_gap_analysis=_gap_analysis(),
    )
    result = await monitor.scan([goal], now=now)
    assert result.breaches == []
    assert result.emitted_intents == 0


@pytest.mark.asyncio
async def test_scan_warning_tier() -> None:
    """Goal active 1.5h with gaps → warning tier."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(), router)
    now = datetime.now(UTC)
    goal = _goal(
        started_at=now - timedelta(hours=1, minutes=30),
        last_gap_analysis=_gap_analysis(),
    )
    result = await monitor.scan([goal], now=now)
    assert len(result.breaches) == 1
    assert result.breaches[0].tier == SlaTier.WARNING
    assert result.emitted_intents == 1
    assert seen[0].kind == "sla.overdue"
    assert seen[0].severity == "warning"


@pytest.mark.asyncio
async def test_scan_critical_tier() -> None:
    """Goal active 3h with gaps → critical tier."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(), router)
    now = datetime.now(UTC)
    goal = _goal(
        started_at=now - timedelta(hours=3),
        last_gap_analysis=_gap_analysis(),
    )
    result = await monitor.scan([goal], now=now)
    assert len(result.breaches) == 1
    assert result.breaches[0].tier == SlaTier.CRITICAL
    assert result.emitted_intents == 1
    assert seen[0].severity == "error"


@pytest.mark.asyncio
async def test_scan_breach_tier() -> None:
    """Goal active 5h with gaps → breach tier."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(), router)
    now = datetime.now(UTC)
    goal = _goal(
        started_at=now - timedelta(hours=5),
        last_gap_analysis=_gap_analysis(),
    )
    result = await monitor.scan([goal], now=now)
    assert len(result.breaches) == 1
    assert result.breaches[0].tier == SlaTier.BREACH
    assert result.emitted_intents == 1
    assert seen[0].severity == "error"


@pytest.mark.asyncio
async def test_scan_below_threshold_no_breach() -> None:
    """Goal active 30min (below 1h warning) → no breach."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(), router)
    now = datetime.now(UTC)
    goal = _goal(
        started_at=now - timedelta(minutes=30),
        last_gap_analysis=_gap_analysis(),
    )
    result = await monitor.scan([goal], now=now)
    assert result.breaches == []
    assert result.emitted_intents == 0
    assert not seen


@pytest.mark.asyncio
async def test_scan_terminal_goals_skipped() -> None:
    """Completed/failed goals are not scanned."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(), router)
    now = datetime.now(UTC)
    completed = _goal(
        status="completed",
        started_at=now - timedelta(hours=5),
        last_gap_analysis=_gap_analysis(),
    )
    failed = _goal(
        id="goal0002",
        status="failed",
        started_at=now - timedelta(hours=5),
        last_gap_analysis=_gap_analysis(),
    )
    result = await monitor.scan([completed, failed], now=now)
    assert result.breaches == []
    assert not seen


@pytest.mark.asyncio
async def test_scan_dedup_same_tier() -> None:
    """Same goal+tier scanned twice → dedup suppresses second alert."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(), router)
    now = datetime.now(UTC)
    goal = _goal(
        started_at=now - timedelta(hours=2),
        last_gap_analysis=_gap_analysis(),
    )
    result1 = await monitor.scan([goal], now=now)
    result2 = await monitor.scan([goal], now=now)
    assert result1.emitted_intents == 1
    assert result2.emitted_intents == 0
    assert result2.skipped_by_dedup == 1
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_scan_multiple_goals() -> None:
    """Multiple overdue goals → multiple breaches."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(), router)
    now = datetime.now(UTC)
    goal_a = _goal(
        id="goal0001",
        started_at=now - timedelta(hours=1, minutes=30),
        last_gap_analysis=_gap_analysis(),
    )
    goal_b = _goal(
        id="goal0002",
        started_at=now - timedelta(hours=3),
        last_gap_analysis=_gap_analysis(remaining_gaps=["Docs missing"]),
    )
    result = await monitor.scan([goal_a, goal_b], now=now)
    assert len(result.breaches) == 2
    assert result.breaches[0].tier == SlaTier.WARNING
    assert result.breaches[1].tier == SlaTier.CRITICAL
    assert result.emitted_intents == 2
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_scan_suspended_goal_with_gaps() -> None:
    """Suspended goals with gaps are still monitored."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(), router)
    now = datetime.now(UTC)
    goal = _goal(
        status="suspended",
        started_at=now - timedelta(hours=2),
        last_gap_analysis=_gap_analysis(),
    )
    result = await monitor.scan([goal], now=now)
    assert len(result.breaches) == 1
    assert result.emitted_intents == 1


@pytest.mark.asyncio
async def test_scan_uses_created_at_when_no_started_at() -> None:
    """Goals without started_at fall back to created_at."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(), router)
    now = datetime.now(UTC)
    goal = _goal(
        status="pending",
        started_at=None,
        last_gap_analysis=_gap_analysis(),
    )
    # Set created_at to 90m ago (above warning threshold 3600s, below critical 7200s)
    goal.created_at = now - timedelta(hours=1, minutes=30)
    result = await monitor.scan([goal], now=now)
    assert len(result.breaches) == 1
    assert result.breaches[0].tier == SlaTier.WARNING


@pytest.mark.asyncio
async def test_intent_metadata_contains_sla_fields() -> None:
    """Dispatched intent carries SLA metadata."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(), router)
    now = datetime.now(UTC)
    goal = _goal(
        started_at=now - timedelta(hours=3),
        last_gap_analysis=_gap_analysis(distance="far"),
    )
    await monitor.scan([goal], now=now)
    assert seen
    meta = seen[0].metadata
    assert meta["sla_tier"] == "critical"
    assert meta["elapsed_seconds"] >= 7200
    assert meta["distance_from_goal"] == "far"
    assert meta["unresolved_components"] == 2


@pytest.mark.asyncio
async def test_scan_result_fields() -> None:
    """SlaMonitorResult carries scanned count and breaches."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    router = NotificationRouter(_notify_cfg(), dispatch_fn=_dispatch)
    monitor = SlaMonitor(_sla_cfg(), router)
    now = datetime.now(UTC)
    goals = [
        _goal(
            started_at=now - timedelta(hours=2),
            last_gap_analysis=_gap_analysis(),
        ),
        _goal(
            id="goal0002",
            status="completed",
            started_at=now - timedelta(hours=2),
            last_gap_analysis=_gap_analysis(),
        ),
    ]
    result = await monitor.scan(goals, now=now)
    assert result.scanned == 2
    assert len(result.breaches) == 1
    assert result.emitted_intents == 1
    assert result.scanned_at == now
