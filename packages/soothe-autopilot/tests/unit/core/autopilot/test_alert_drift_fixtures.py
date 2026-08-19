"""CI-runnable validation for synthetic alert drift fixtures.

Exercises every cataloged ``AlertScenario`` from
``tests/fixtures/alert_scenarios.py`` against the real SLA monitor and
notification router, asserting the expected kind / tier / severity /
intent count / dedup behavior. Runs as a standard unit test (no external
services, no LLM API keys) — CI-runnable by default.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fixtures.alert_scenarios import (
    ALL_ALERT_SCENARIOS,
    REF_NOW,
    SCENARIOS_BY_ID,
    AlertScenario,
)
from soothe.config.models import (
    AutopilotNotifyConfig,
    NotifyEventsConfig,
    NotifyTargetConfig,
    SlaConfig,
)
from soothe.context.models import GoalNode

from soothe_autopilot.notify import NotificationRouter, NotifyIntent
from soothe_autopilot.sla import SlaMonitor, SlaTier

# ──────────────────────────────────────────────────────────────────────────
# Builders that materialize a scenario into real soothe objects
# ──────────────────────────────────────────────────────────────────────────


def _build_sla_config(scenario: AlertScenario) -> SlaConfig:
    """Build a SlaConfig from the scenario's sla_config_kwargs."""
    base = SlaConfig(
        enabled=True,
        warning_seconds=3600,
        critical_seconds=7200,
        breach_seconds=14400,
    )
    return base.model_copy(update=scenario.sla_config_kwargs)


def _build_notify_config(
    scenario: AlertScenario,
    *,
    sla: SlaConfig | None = None,
) -> AutopilotNotifyConfig:
    """Build an AutopilotNotifyConfig from the scenario's notify_config_kwargs."""
    base = AutopilotNotifyConfig(
        enabled=True,
        events=NotifyEventsConfig(),
        targets=[NotifyTargetConfig(kind="email", to_address="ops@example.com")],
        sla=sla or _build_sla_config(scenario),
    )
    return base.model_copy(update=scenario.notify_config_kwargs)


def _build_goal(scenario: AlertScenario) -> GoalNode:
    """Build a GoalNode from the scenario's goal_kwargs.

    For SLA scenarios that rely on created_at fallback (started_at=None) and
    do not set created_at explicitly, default created_at to 1.5h ago so
    elapsed lands in the WARNING tier.
    """
    kwargs = dict(scenario.goal_kwargs)
    # If started_at is None and created_at is not set, default to 1.5h ago
    # so SLA WARNING tier fires (5400s >= 3600s warning, < 7200s critical).
    if kwargs.get("started_at") is None and "created_at" not in kwargs:
        kwargs["created_at"] = REF_NOW - timedelta(hours=1, minutes=30)
    return GoalNode(**kwargs)


def _make_router(scenario: AlertScenario) -> NotificationRouter:
    """Build a NotificationRouter with a capturing dispatch_fn."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    cfg = _build_notify_config(scenario)
    router = NotificationRouter(cfg, dispatch_fn=_dispatch)
    # Attach the seen list so the test can inspect dispatched intents.
    router._test_seen = seen  # type: ignore[attr-defined]
    return router


# ──────────────────────────────────────────────────────────────────────────
# Catalog integrity tests
# ──────────────────────────────────────────────────────────────────────────


def test_catalog_has_all_expected_scenarios() -> None:
    """Every cataloged alert scenario is present in ALL_ALERT_SCENARIOS."""
    expected_ids = {
        "sla_no_gaps_no_breach",
        "sla_disabled_no_scan",
        "sla_warning_tier",
        "sla_critical_tier",
        "sla_breach_tier",
        "sla_below_threshold_no_breach",
        "sla_terminal_goals_skipped",
        "sla_dedup_same_tier",
        "sla_suspended_goal_with_gaps",
        "sla_created_at_fallback",
        "job_completed_clean_info",
        "job_completed_with_failed_children_warning",
        "job_completed_maturity_blockers_warning",
        "job_completed_acceptance_not_met_warning",
        "job_failed_error",
        "job_suspended_timeout_warning",
        "job_suspended_timeout_far_past_error",
        "job_suspended_custom_multiplier_error",
        "job_suspended_custom_multiplier_still_warning",
        "job_child_goal_ignored",
        "job_notify_disabled_noop",
        "dedup_same_intent_blocked",
        "dedup_ttl_zero_no_expiry",
        "cfg_critical_below_warning_rejected",
        "cfg_breach_below_critical_rejected",
        "cfg_zero_thresholds_disable_tier",
    }
    actual_ids = {s.id for s in ALL_ALERT_SCENARIOS}
    missing = expected_ids - actual_ids
    extra = actual_ids - expected_ids
    assert not missing, f"Missing scenarios: {missing}"
    assert not extra, f"Unexpected scenarios: {extra}"


def test_scenario_ids_unique() -> None:
    """All scenario ids are unique."""
    ids = [s.id for s in ALL_ALERT_SCENARIOS]
    assert len(ids) == len(set(ids)), "Duplicate scenario ids found"


def test_scenarios_by_id_matches_list() -> None:
    """SCENARIOS_BY_ID index matches ALL_ALERT_SCENARIOS."""
    assert len(SCENARIOS_BY_ID) == len(ALL_ALERT_SCENARIOS)
    for scenario in ALL_ALERT_SCENARIOS:
        assert SCENARIOS_BY_ID[scenario.id] is scenario


def test_scenario_groups_are_valid() -> None:
    """Every scenario belongs to a known group."""
    valid_groups = {"SLA", "JOB", "DEDUP", "CFG"}
    for s in ALL_ALERT_SCENARIOS:
        assert s.group in valid_groups, f"{s.id} has invalid group {s.group!r}"


# ──────────────────────────────────────────────────────────────────────────
# Config validation scenarios (CFG group)
# ──────────────────────────────────────────────────────────────────────────


def test_cfg_critical_below_warning_rejected() -> None:
    """SlaConfig rejects critical_seconds < warning_seconds."""
    scenario = SCENARIOS_BY_ID["cfg_critical_below_warning_rejected"]
    with pytest.raises(ValueError, match="critical_seconds"):
        SlaConfig(**scenario.sla_config_kwargs)


def test_cfg_breach_below_critical_rejected() -> None:
    """SlaConfig rejects breach_seconds < critical_seconds."""
    scenario = SCENARIOS_BY_ID["cfg_breach_below_critical_rejected"]
    with pytest.raises(ValueError, match="breach_seconds"):
        SlaConfig(**scenario.sla_config_kwargs)


def test_cfg_zero_thresholds_disable_tier() -> None:
    """All-zero thresholds produce no breach (tiers disabled, no raise)."""
    scenario = SCENARIOS_BY_ID["cfg_zero_thresholds_disable_tier"]
    cfg = SlaConfig(**scenario.sla_config_kwargs)
    assert cfg.warning_seconds == 0
    assert cfg.critical_seconds == 0
    assert cfg.breach_seconds == 0

    # Build monitor and scan — should produce no breaches.
    router = _make_router(scenario)
    monitor = SlaMonitor(cfg, router)
    goal = _build_goal(scenario)

    result = asyncio.run(monitor.scan([goal], now=scenario.now_override))
    assert len(result.breaches) == 0
    assert result.emitted_intents == 0


# ──────────────────────────────────────────────────────────────────────────
# SLA monitor scenarios (SLA group)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sla_no_gaps_no_breach() -> None:
    """Active goal with no gap analysis → no breach."""
    scenario = SCENARIOS_BY_ID["sla_no_gaps_no_breach"]
    router = _make_router(scenario)
    monitor = SlaMonitor(_build_sla_config(scenario), router)
    goal = _build_goal(scenario)
    result = await monitor.scan([goal], now=scenario.now_override)
    assert len(result.breaches) == 0
    assert result.emitted_intents == 0
    assert result.skipped_by_dedup == 0


@pytest.mark.asyncio
async def test_sla_disabled_no_scan() -> None:
    """SLA monitor disabled → scan returns empty result."""
    scenario = SCENARIOS_BY_ID["sla_disabled_no_scan"]
    router = _make_router(scenario)
    monitor = SlaMonitor(_build_sla_config(scenario), router)
    goal = _build_goal(scenario)
    result = await monitor.scan([goal], now=scenario.now_override)
    assert result.scanned == 0  # disabled returns empty SlaMonitorResult
    assert len(result.breaches) == 0
    assert result.emitted_intents == 0


@pytest.mark.asyncio
async def test_sla_warning_tier() -> None:
    """Active 1.5h with gaps → WARNING tier."""
    scenario = SCENARIOS_BY_ID["sla_warning_tier"]
    router = _make_router(scenario)
    monitor = SlaMonitor(_build_sla_config(scenario), router)
    goal = _build_goal(scenario)
    result = await monitor.scan([goal], now=scenario.now_override)
    assert len(result.breaches) == 1
    breach = result.breaches[0]
    assert breach.tier == SlaTier.WARNING
    assert result.emitted_intents == 1
    assert result.skipped_by_dedup == 0
    seen: list[NotifyIntent] = router._test_seen  # type: ignore[attr-defined]
    assert seen[0].kind == "sla.overdue"
    assert seen[0].severity == "warning"


@pytest.mark.asyncio
async def test_sla_critical_tier() -> None:
    """Active 3h with gaps → CRITICAL tier."""
    scenario = SCENARIOS_BY_ID["sla_critical_tier"]
    router = _make_router(scenario)
    monitor = SlaMonitor(_build_sla_config(scenario), router)
    goal = _build_goal(scenario)
    result = await monitor.scan([goal], now=scenario.now_override)
    assert len(result.breaches) == 1
    assert result.breaches[0].tier == SlaTier.CRITICAL
    assert result.emitted_intents == 1
    seen: list[NotifyIntent] = router._test_seen  # type: ignore[attr-defined]
    assert seen[0].kind == "sla.overdue"
    assert seen[0].severity == "error"


@pytest.mark.asyncio
async def test_sla_breach_tier() -> None:
    """Active 5h with gaps → BREACH tier."""
    scenario = SCENARIOS_BY_ID["sla_breach_tier"]
    router = _make_router(scenario)
    monitor = SlaMonitor(_build_sla_config(scenario), router)
    goal = _build_goal(scenario)
    result = await monitor.scan([goal], now=scenario.now_override)
    assert len(result.breaches) == 1
    assert result.breaches[0].tier == SlaTier.BREACH
    assert result.emitted_intents == 1
    seen: list[NotifyIntent] = router._test_seen  # type: ignore[attr-defined]
    assert seen[0].kind == "sla.overdue"
    assert seen[0].severity == "error"


@pytest.mark.asyncio
async def test_sla_below_threshold_no_breach() -> None:
    """Active 30min with gaps → below warning threshold, no breach."""
    scenario = SCENARIOS_BY_ID["sla_below_threshold_no_breach"]
    router = _make_router(scenario)
    monitor = SlaMonitor(_build_sla_config(scenario), router)
    goal = _build_goal(scenario)
    result = await monitor.scan([goal], now=scenario.now_override)
    assert len(result.breaches) == 0
    assert result.emitted_intents == 0


@pytest.mark.asyncio
async def test_sla_terminal_goals_skipped() -> None:
    """Completed goals are skipped (not in _ACTIVE_STATUSES)."""
    scenario = SCENARIOS_BY_ID["sla_terminal_goals_skipped"]
    router = _make_router(scenario)
    monitor = SlaMonitor(_build_sla_config(scenario), router)
    goal = _build_goal(scenario)
    result = await monitor.scan([goal], now=scenario.now_override)
    assert len(result.breaches) == 0
    assert result.emitted_intents == 0


@pytest.mark.asyncio
async def test_sla_dedup_same_tier() -> None:
    """Same goal+tier re-scan → dedup suppresses second alert."""
    scenario = SCENARIOS_BY_ID["sla_dedup_same_tier"]
    router = _make_router(scenario)
    monitor = SlaMonitor(_build_sla_config(scenario), router)
    goal = _build_goal(scenario)
    # First scan — should emit.
    result1 = await monitor.scan([goal], now=scenario.now_override)
    assert result1.emitted_intents == 1
    assert result1.skipped_by_dedup == 0
    assert result1.breaches[0].tier == SlaTier.CRITICAL
    # Second scan — same goal+tier → deduped.
    result2 = await monitor.scan([goal], now=scenario.now_override)
    assert result2.emitted_intents == 0
    assert result2.skipped_by_dedup == 1
    seen: list[NotifyIntent] = router._test_seen  # type: ignore[attr-defined]
    assert len(seen) == 1  # only first intent dispatched


@pytest.mark.asyncio
async def test_sla_suspended_goal_with_gaps() -> None:
    """Suspended goal with gaps still monitored (suspended is active)."""
    scenario = SCENARIOS_BY_ID["sla_suspended_goal_with_gaps"]
    router = _make_router(scenario)
    monitor = SlaMonitor(_build_sla_config(scenario), router)
    goal = _build_goal(scenario)
    result = await monitor.scan([goal], now=scenario.now_override)
    assert len(result.breaches) == 1
    assert result.breaches[0].tier == SlaTier.CRITICAL
    assert result.emitted_intents == 1


@pytest.mark.asyncio
async def test_sla_created_at_fallback() -> None:
    """No started_at → uses created_at for elapsed calc."""
    scenario = SCENARIOS_BY_ID["sla_created_at_fallback"]
    router = _make_router(scenario)
    monitor = SlaMonitor(_build_sla_config(scenario), router)
    goal = _build_goal(scenario)
    # created_at is set to 2h ago by _build_goal → WARNING tier.
    result = await monitor.scan([goal], now=scenario.now_override)
    assert len(result.breaches) == 1
    assert result.breaches[0].tier == SlaTier.WARNING
    assert result.emitted_intents == 1


# ──────────────────────────────────────────────────────────────────────────
# Job lifecycle notify scenarios (JOB group)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_completed_clean_info() -> None:
    """Completed root, no failed/active children → info severity."""
    scenario = SCENARIOS_BY_ID["job_completed_clean_info"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    intent = await router.on_job_root_status(goal, progress=scenario.progress)
    assert intent is not None
    assert intent.kind == "job.completed"
    assert intent.severity == "info"
    seen: list[NotifyIntent] = router._test_seen  # type: ignore[attr-defined]
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_job_completed_with_failed_children_warning() -> None:
    """Completed root but children failed → warning (completion drift)."""
    scenario = SCENARIOS_BY_ID["job_completed_with_failed_children_warning"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    intent = await router.on_job_root_status(goal, progress=scenario.progress)
    assert intent is not None
    assert intent.kind == "job.completed"
    assert intent.severity == "warning"


@pytest.mark.asyncio
async def test_job_completed_maturity_blockers_warning() -> None:
    """Completed root with maturity blockers → warning (acceptance drift)."""
    scenario = SCENARIOS_BY_ID["job_completed_maturity_blockers_warning"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    intent = await router.on_job_root_status(goal)
    assert intent is not None
    assert intent.kind == "job.completed"
    assert intent.severity == "warning"


@pytest.mark.asyncio
async def test_job_completed_acceptance_not_met_warning() -> None:
    """Completed root with acceptance_met=False → warning."""
    scenario = SCENARIOS_BY_ID["job_completed_acceptance_not_met_warning"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    intent = await router.on_job_root_status(goal)
    assert intent is not None
    assert intent.kind == "job.completed"
    assert intent.severity == "warning"


@pytest.mark.asyncio
async def test_job_failed_error() -> None:
    """Failed root is always error severity."""
    scenario = SCENARIOS_BY_ID["job_failed_error"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    intent = await router.on_job_root_status(goal)
    assert intent is not None
    assert intent.kind == "job.failed"
    assert intent.severity == "error"


@pytest.mark.asyncio
async def test_job_suspended_timeout_warning() -> None:
    """Suspended timeout just past threshold → warning."""
    scenario = SCENARIOS_BY_ID["job_suspended_timeout_warning"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    emitted = await router.scan_suspended_timeouts([goal], now=scenario.now_override)
    assert len(emitted) == 1
    assert emitted[0].kind == "job.suspended_timeout"
    assert emitted[0].severity == "warning"


@pytest.mark.asyncio
async def test_job_suspended_timeout_far_past_error() -> None:
    """Suspended timeout at >=2x threshold → error (drift past suspend window)."""
    scenario = SCENARIOS_BY_ID["job_suspended_timeout_far_past_error"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    emitted = await router.scan_suspended_timeouts([goal], now=scenario.now_override)
    assert len(emitted) == 1
    assert emitted[0].kind == "job.suspended_timeout"
    assert emitted[0].severity == "error"


@pytest.mark.asyncio
async def test_job_suspended_custom_multiplier_error() -> None:
    """Suspended at >=3x threshold with multiplier=3.0 → error."""
    scenario = SCENARIOS_BY_ID["job_suspended_custom_multiplier_error"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    emitted = await router.scan_suspended_timeouts([goal], now=scenario.now_override)
    assert len(emitted) == 1
    assert emitted[0].severity == "error"


@pytest.mark.asyncio
async def test_job_suspended_custom_multiplier_still_warning() -> None:
    """Suspended between 1x and 3x threshold with multiplier=3.0 → warning."""
    scenario = SCENARIOS_BY_ID["job_suspended_custom_multiplier_still_warning"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    emitted = await router.scan_suspended_timeouts([goal], now=scenario.now_override)
    assert len(emitted) == 1
    assert emitted[0].severity == "warning"


@pytest.mark.asyncio
async def test_job_child_goal_ignored() -> None:
    """Child goals (parent_id set) are ignored by router."""
    scenario = SCENARIOS_BY_ID["job_child_goal_ignored"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    intent = await router.on_job_root_status(goal, progress=scenario.progress)
    assert intent is None
    seen: list[NotifyIntent] = router._test_seen  # type: ignore[attr-defined]
    assert len(seen) == 0


@pytest.mark.asyncio
async def test_job_notify_disabled_noop() -> None:
    """Notify config disabled → router is a no-op."""
    scenario = SCENARIOS_BY_ID["job_notify_disabled_noop"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    intent = await router.on_job_root_status(goal)
    assert intent is None
    seen: list[NotifyIntent] = router._test_seen  # type: ignore[attr-defined]
    assert len(seen) == 0


# ──────────────────────────────────────────────────────────────────────────
# Dedup / TTL scenarios (DEDUP group)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dedup_same_intent_blocked() -> None:
    """Same intent emitted twice → second is deduped."""
    scenario = SCENARIOS_BY_ID["dedup_same_intent_blocked"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    first = await router.on_job_root_status(goal)
    assert first is not None
    assert first.kind == "job.failed"
    assert first.severity == "error"
    second = await router.on_job_root_status(goal)
    assert second is None
    seen: list[NotifyIntent] = router._test_seen  # type: ignore[attr-defined]
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_dedup_ttl_zero_no_expiry() -> None:
    """TTL=0 means no expiry (keys persist indefinitely)."""
    scenario = SCENARIOS_BY_ID["dedup_ttl_zero_no_expiry"]
    router = _make_router(scenario)
    goal = _build_goal(scenario)
    first = await router.on_job_root_status(goal)
    assert first is not None
    second = await router.on_job_root_status(goal)
    assert second is None
    seen: list[NotifyIntent] = router._test_seen  # type: ignore[attr-defined]
    assert len(seen) == 1


# ──────────────────────────────────────────────────────────────────────────
# Parametrized smoke test — every scenario is materializable
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "scenario",
    ALL_ALERT_SCENARIOS,
    ids=[s.id for s in ALL_ALERT_SCENARIOS],
)
def test_every_scenario_is_materializable(scenario: AlertScenario) -> None:
    """Every cataloged scenario can be materialized into config + goal objects
    without raising (config validation scenarios are expected to raise and
    are skipped here — they have their own dedicated tests)."""
    if scenario.group == "CFG" and "rejected" in scenario.id:
        pytest.skip("Config rejection scenarios have dedicated tests")
    # Build sla config (may use defaults).
    sla = _build_sla_config(scenario)
    # Build notify config (always succeeds — CFG validation is on SlaConfig only).
    _build_notify_config(scenario, sla=sla)
    # Build goal (may have minimal kwargs).
    goal = _build_goal(scenario)
    assert goal.id == scenario.goal_kwargs.get("id")
