"""Latency SLO checks for the alert/drift-detection pipeline.

CI-runnable pytest tests that measure end-to-end latency of:
    GoalNode → SlaMonitor.scan → NotificationRouter.emit_sla_overdue → NotifyIntent
    GoalNode → NotificationRouter.emit_job_intent → NotifyIntent
    GoalNode → NotificationRouter.scan_suspended_timeouts → list[NotifyIntent]

Each test asserts that the measured p99 latency stays within the SLO budget
defined in ``SLO_THRESHOLDS_MS``. Runs fully offline (no LLM, no external
services) — CI-runnable by default.

These tests complement ``scripts/benchmark_alert_pipeline.py`` (the full
benchmark runner with JSON/markdown reporting) by providing fast, focused
SLO assertions that run as part of the standard unit test suite.
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta

import pytest
from fixtures.alert_scenarios import (
    REF_NOW,
    SCENARIOS_BY_ID,
)
from soothe.config.models import (
    AutopilotNotifyConfig,
    NotifyEventsConfig,
    NotifyTargetConfig,
    SlaConfig,
)
from soothe.context.models import GoalNode

from soothe_autopilot.notify import NotificationRouter, NotifyIntent
from soothe_autopilot.notify.dedup import NotifyDedupStore
from soothe_autopilot.sla import SlaMonitor

# ──────────────────────────────────────────────────────────────────────────
# SLO Thresholds (ms) — must match scripts/benchmark_alert_pipeline.py
# ──────────────────────────────────────────────────────────────────────────

SLO_THRESHOLDS_MS: dict[str, float] = {
    "sla_scan_single_goal_p99": 5.0,
    "sla_scan_batch_per_goal_p99": 2.0,
    "job_intent_emit_p99": 5.0,
    "suspended_scan_per_root_p99": 3.0,
    "dedup_check_p99": 2.0,
    "e2e_single_goal_p99": 10.0,
    "e2e_batch_50_total_p99": 100.0,
}

# Iterations for latency measurement. Low enough for fast CI, high enough
# for a stable p99 estimate.
_ITERATIONS = 100


# ──────────────────────────────────────────────────────────────────────────
# Builders (mirror test_alert_drift_fixtures.py conventions)
# ──────────────────────────────────────────────────────────────────────────


def _build_sla_config(scenario) -> SlaConfig:
    """Build a SlaConfig from the scenario's sla_config_kwargs."""
    base = SlaConfig(
        enabled=True,
        warning_seconds=3600,
        critical_seconds=7200,
        breach_seconds=14400,
    )
    return base.model_copy(update=scenario.sla_config_kwargs)


def _build_notify_config(
    scenario,
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


def _build_goal(scenario) -> GoalNode:
    """Build a GoalNode from the scenario's goal_kwargs."""
    kwargs = dict(scenario.goal_kwargs)
    if kwargs.get("started_at") is None and "created_at" not in kwargs:
        kwargs["created_at"] = REF_NOW - timedelta(hours=1, minutes=30)
    return GoalNode(**kwargs)


def _make_router(scenario) -> tuple[NotificationRouter, list[NotifyIntent]]:
    """Build a NotificationRouter with a capturing dispatch_fn."""
    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    cfg = _build_notify_config(scenario)
    router = NotificationRouter(cfg, dispatch_fn=_dispatch)
    return router, seen


def _percentile(values: list[float], pct: float) -> float:
    """Compute the pct percentile (0.0–1.0) of a list."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    idx = int(n * pct)
    if idx >= n:
        idx = n - 1
    return sorted_vals[idx]


def _measure_async(fn, iterations: int) -> list[float]:
    """Measure async callable latency in ms across N iterations."""
    latencies: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        asyncio.get_event_loop().run_until_complete(fn())
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
    return latencies


# ──────────────────────────────────────────────────────────────────────────
# SLA scan latency SLO tests
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slo_sla_scan_single_goal_p99() -> None:
    """SLO: SLA scan of a single goal must complete under 5.0 ms p99.

    Exercises: SlaMonitor.scan([goal]) → _extract_gap_items →
    _classify_tier → SlaBreach construction → router.emit_sla_overdue →
    dedup check + dispatch.
    """
    scenario = SCENARIOS_BY_ID["sla_warning_tier"]
    threshold = SLO_THRESHOLDS_MS["sla_scan_single_goal_p99"]

    latencies: list[float] = []
    for _ in range(_ITERATIONS):
        router, _ = _make_router(scenario)
        monitor = SlaMonitor(_build_sla_config(scenario), router)
        goal = _build_goal(scenario)
        now = scenario.now_override

        t0 = time.perf_counter()
        await monitor.scan([goal], now=now)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p99 = _percentile(latencies, 0.99)
    assert p99 <= threshold, f"SLA scan single-goal p99={p99:.4f}ms exceeds SLO {threshold}ms"


@pytest.mark.asyncio
async def test_slo_sla_scan_critical_tier_p99() -> None:
    """SLO: SLA scan at CRITICAL tier must complete under 5.0 ms p99."""
    scenario = SCENARIOS_BY_ID["sla_critical_tier"]
    threshold = SLO_THRESHOLDS_MS["sla_scan_single_goal_p99"]

    latencies: list[float] = []
    for _ in range(_ITERATIONS):
        router, _ = _make_router(scenario)
        monitor = SlaMonitor(_build_sla_config(scenario), router)
        goal = _build_goal(scenario)
        now = scenario.now_override

        t0 = time.perf_counter()
        await monitor.scan([goal], now=now)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p99 = _percentile(latencies, 0.99)
    assert p99 <= threshold, f"SLA scan critical-tier p99={p99:.4f}ms exceeds SLO {threshold}ms"


@pytest.mark.asyncio
async def test_slo_sla_scan_breach_tier_p99() -> None:
    """SLO: SLA scan at BREACH tier must complete under 5.0 ms p99."""
    scenario = SCENARIOS_BY_ID["sla_breach_tier"]
    threshold = SLO_THRESHOLDS_MS["sla_scan_single_goal_p99"]

    latencies: list[float] = []
    for _ in range(_ITERATIONS):
        router, _ = _make_router(scenario)
        monitor = SlaMonitor(_build_sla_config(scenario), router)
        goal = _build_goal(scenario)
        now = scenario.now_override

        t0 = time.perf_counter()
        await monitor.scan([goal], now=now)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p99 = _percentile(latencies, 0.99)
    assert p99 <= threshold, f"SLA scan breach-tier p99={p99:.4f}ms exceeds SLO {threshold}ms"


# ──────────────────────────────────────────────────────────────────────────
# Job intent emit latency SLO tests
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slo_job_completed_intent_emit_p99() -> None:
    """SLO: job.completed intent emit must complete under 5.0 ms p99.

    Exercises: router.emit_job_intent("job.completed", goal, progress) →
    _severity_for → _title_for → _body_for → NotifyIntent construction →
    dedup check + dispatch.
    """
    scenario = SCENARIOS_BY_ID["job_completed_clean_info"]
    threshold = SLO_THRESHOLDS_MS["job_intent_emit_p99"]

    latencies: list[float] = []
    for _ in range(_ITERATIONS):
        router, _ = _make_router(scenario)
        goal = _build_goal(scenario)

        t0 = time.perf_counter()
        await router.emit_job_intent("job.completed", goal, progress=scenario.progress)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p99 = _percentile(latencies, 0.99)
    assert p99 <= threshold, f"job.completed intent emit p99={p99:.4f}ms exceeds SLO {threshold}ms"


@pytest.mark.asyncio
async def test_slo_job_failed_intent_emit_p99() -> None:
    """SLO: job.failed intent emit must complete under 5.0 ms p99."""
    scenario = SCENARIOS_BY_ID["job_failed_error"]
    threshold = SLO_THRESHOLDS_MS["job_intent_emit_p99"]

    latencies: list[float] = []
    for _ in range(_ITERATIONS):
        router, _ = _make_router(scenario)
        goal = _build_goal(scenario)

        t0 = time.perf_counter()
        await router.emit_job_intent("job.failed", goal)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p99 = _percentile(latencies, 0.99)
    assert p99 <= threshold, f"job.failed intent emit p99={p99:.4f}ms exceeds SLO {threshold}ms"


@pytest.mark.asyncio
async def test_slo_job_completed_drift_warning_p99() -> None:
    """SLO: job.completed with drift (failed children) → warning severity, under 5.0 ms p99.

    Exercises the drift-aware severity escalation path (progress dict with
    failed_goals > 0 → info → warning).
    """
    scenario = SCENARIOS_BY_ID["job_completed_with_failed_children_warning"]
    threshold = SLO_THRESHOLDS_MS["job_intent_emit_p99"]

    latencies: list[float] = []
    for _ in range(_ITERATIONS):
        router, _ = _make_router(scenario)
        goal = _build_goal(scenario)

        t0 = time.perf_counter()
        await router.emit_job_intent("job.completed", goal, progress=scenario.progress)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p99 = _percentile(latencies, 0.99)
    assert p99 <= threshold, (
        f"job.completed drift-warning p99={p99:.4f}ms exceeds SLO {threshold}ms"
    )


# ──────────────────────────────────────────────────────────────────────────
# Suspended-timeout scan latency SLO tests
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slo_suspended_scan_per_root_p99() -> None:
    """SLO: suspended-timeout scan per root must complete under 3.0 ms p99.

    Exercises: router.scan_suspended_timeouts([root], now) → per-root
    age calculation → threshold comparison → emit_job_intent for
    suspended_timeout.
    """
    scenario = SCENARIOS_BY_ID["job_suspended_timeout_warning"]
    threshold = SLO_THRESHOLDS_MS["suspended_scan_per_root_p99"]

    latencies: list[float] = []
    for _ in range(_ITERATIONS):
        router, _ = _make_router(scenario)
        goal = _build_goal(scenario)
        now = scenario.now_override

        t0 = time.perf_counter()
        await router.scan_suspended_timeouts([goal], now=now)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p99 = _percentile(latencies, 0.99)
    assert p99 <= threshold, f"suspended scan per-root p99={p99:.4f}ms exceeds SLO {threshold}ms"


@pytest.mark.asyncio
async def test_slo_suspended_scan_escalation_error_p99() -> None:
    """SLO: suspended-timeout scan with drift escalation (error) under 3.0 ms p99.

    Exercises the suspend_escalation_multiplier path: age > 2x threshold
    → error severity (drift past suspend window).
    """
    scenario = SCENARIOS_BY_ID["job_suspended_timeout_far_past_error"]
    threshold = SLO_THRESHOLDS_MS["suspended_scan_per_root_p99"]

    latencies: list[float] = []
    for _ in range(_ITERATIONS):
        router, _ = _make_router(scenario)
        goal = _build_goal(scenario)
        now = scenario.now_override

        t0 = time.perf_counter()
        await router.scan_suspended_timeouts([goal], now=now)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p99 = _percentile(latencies, 0.99)
    assert p99 <= threshold, f"suspended scan escalation p99={p99:.4f}ms exceeds SLO {threshold}ms"


# ──────────────────────────────────────────────────────────────────────────
# Dedup check latency SLO tests
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slo_dedup_check_p99() -> None:
    """SLO: dedup already_sent + mark_sent cycle must complete under 2.0 ms p99.

    Exercises: NotifyDedupStore.already_sent(key) → mark_sent(key) on
    the in-memory store (no persist_store configured).
    """
    threshold = SLO_THRESHOLDS_MS["dedup_check_p99"]
    store = NotifyDedupStore(ttl_seconds=86400)

    latencies: list[float] = []
    for i in range(_ITERATIONS):
        key = f"slo_dedup_test:{i}"
        t0 = time.perf_counter()
        already = await store.already_sent(key)
        if not already:
            await store.mark_sent(key)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p99 = _percentile(latencies, 0.99)
    assert p99 <= threshold, f"dedup check p99={p99:.4f}ms exceeds SLO {threshold}ms"


# ──────────────────────────────────────────────────────────────────────────
# End-to-end latency SLO tests
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slo_e2e_single_goal_p99() -> None:
    """SLO: full end-to-end single-goal pipeline under 10.0 ms p99.

    Exercises the complete chain: GoalNode → SlaMonitor.scan →
    _extract_gap_items → _classify_tier → SlaBreach →
    router.emit_sla_overdue → NotifyIntent → dedup → dispatch.
    """
    scenario = SCENARIOS_BY_ID["sla_warning_tier"]
    threshold = SLO_THRESHOLDS_MS["e2e_single_goal_p99"]

    latencies: list[float] = []
    for _ in range(_ITERATIONS):
        router, seen = _make_router(scenario)
        monitor = SlaMonitor(_build_sla_config(scenario), router)
        goal = _build_goal(scenario)
        now = scenario.now_override

        t0 = time.perf_counter()
        result = await monitor.scan([goal], now=now)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
        _ = len(seen)  # prevent dead-code elimination
        _ = result

    p99 = _percentile(latencies, 0.99)
    assert p99 <= threshold, f"e2e single-goal p99={p99:.4f}ms exceeds SLO {threshold}ms"


@pytest.mark.asyncio
async def test_slo_e2e_batch_50_total_p99() -> None:
    """SLO: 50-goal batch SLA scan total under 100.0 ms p99.

    Exercises: SlaMonitor.scan([50 goals]) — the realistic watchdog-tick
    scenario where the monitor scans the full active DAG snapshot.
    """
    # Build 50 goals from a mix of SLA scenarios (cycle through the
    # scenarios that produce breaches to exercise the full pipeline).
    breach_scenarios = [
        SCENARIOS_BY_ID["sla_warning_tier"],
        SCENARIOS_BY_ID["sla_critical_tier"],
        SCENARIOS_BY_ID["sla_breach_tier"],
        SCENARIOS_BY_ID["sla_suspended_goal_with_gaps"],
        SCENARIOS_BY_ID["sla_created_at_fallback"],
    ]
    goals: list[GoalNode] = []
    for i in range(50):
        scenario = breach_scenarios[i % len(breach_scenarios)]
        goals.append(_build_goal(scenario))

    scenario = breach_scenarios[0]
    threshold = SLO_THRESHOLDS_MS["e2e_batch_50_total_p99"]

    latencies: list[float] = []
    for _ in range(_ITERATIONS):
        router, _ = _make_router(scenario)
        monitor = SlaMonitor(_build_sla_config(scenario), router)
        now = scenario.now_override

        t0 = time.perf_counter()
        await monitor.scan(goals, now=now)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p99 = _percentile(latencies, 0.99)
    assert p99 <= threshold, f"e2e batch-50 total p99={p99:.4f}ms exceeds SLO {threshold}ms"


@pytest.mark.asyncio
async def test_slo_sla_scan_batch_per_goal_amortized_p99() -> None:
    """SLO: amortized per-goal latency in a 50-goal batch under 2.0 ms p99.

    Derived SLO: total batch latency / 50 must stay under the per-goal
    budget. This catches O(n²) regressions in the scan loop.
    """
    breach_scenarios = [
        SCENARIOS_BY_ID["sla_warning_tier"],
        SCENARIOS_BY_ID["sla_critical_tier"],
        SCENARIOS_BY_ID["sla_breach_tier"],
        SCENARIOS_BY_ID["sla_suspended_goal_with_gaps"],
        SCENARIOS_BY_ID["sla_created_at_fallback"],
    ]
    goals: list[GoalNode] = []
    for i in range(50):
        scenario = breach_scenarios[i % len(breach_scenarios)]
        goals.append(_build_goal(scenario))

    scenario = breach_scenarios[0]
    threshold = SLO_THRESHOLDS_MS["sla_scan_batch_per_goal_p99"]

    latencies: list[float] = []
    for _ in range(_ITERATIONS):
        router, _ = _make_router(scenario)
        monitor = SlaMonitor(_build_sla_config(scenario), router)
        now = scenario.now_override

        t0 = time.perf_counter()
        await monitor.scan(goals, now=now)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p99_total = _percentile(latencies, 0.99)
    per_goal_p99 = p99_total / 50.0
    assert per_goal_p99 <= threshold, (
        f"sla scan batch per-goal p99={per_goal_p99:.4f}ms "
        f"(total={p99_total:.4f}ms) exceeds SLO {threshold}ms"
    )
