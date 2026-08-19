#!/usr/bin/env python3
"""Alert Pipeline Performance Benchmark & Latency SLO Checks.

Benchmarks end-to-end latency of the alert/drift-detection pipeline:
    GoalNode → SlaMonitor.scan → NotificationRouter.emit_sla_overdue → NotifyIntent
    GoalNode → NotificationRouter.emit_job_intent → NotifyIntent
    GoalNode → NotificationRouter.scan_suspended_timeouts → list[NotifyIntent]

Measures per-scenario and aggregate latency against SLO thresholds, then
emits a pass/fail SLO report. Runs fully offline (no LLM, no external
services) — CI-runnable by default.

Usage:
    # Run all scenarios, print markdown report
    python scripts/benchmark_alert_pipeline.py

    # JSON output
    python scripts/benchmark_alert_pipeline.py --output json

    # Save report to file
    python scripts/benchmark_alert_pipeline.py --output-file report.md

    # Scale up iterations for tighter percentile estimates
    python scripts/benchmark_alert_pipeline.py --iterations 500

    # SLO-only mode (exit non-zero if any SLO breached)
    python scripts/benchmark_alert_pipeline.py --slo-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Add fixtures directory and package source paths for scenario imports.
# When run from a source checkout (not installed), these ensure the script
# can import fixtures, soothe, and soothe_autopilot without installation.
# Note: fixtures is a package under tests/, so the path must include tests/.
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "packages" / "soothe-autopilot" / "tests"))
sys.path.insert(0, str(_ROOT / "packages" / "soothe-autopilot" / "src"))
sys.path.insert(0, str(_ROOT / "packages" / "soothe" / "src"))
sys.path.insert(0, str(_ROOT / "packages" / "soothe-sdk" / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# SLO Thresholds (measurable latency budgets for end-to-end drift detection)
# ──────────────────────────────────────────────────────────────────────────

# All thresholds are in milliseconds and represent the maximum acceptable
# wall-clock latency for a single end-to-end pipeline traversal.
#
# These are SLO *budgets*, not typical latencies. The pipeline is pure
# Python (no LLM, no network) so typical latencies are sub-millisecond;
# the SLOs leave generous headroom for CI runners, GC pauses, and
# future feature additions.
SLO_THRESHOLDS_MS: dict[str, float] = {
    # Single SLA scan of one goal → SlaMonitor.scan([goal]) → emit_sla_overdue
    "sla_scan_single_goal_p99": 5.0,
    # SLA scan of N goals (batch) — per-goal amortized p99
    "sla_scan_batch_per_goal_p99": 2.0,
    # Single job intent emit — emit_job_intent (completed/failed)
    "job_intent_emit_p99": 5.0,
    # Suspended-timeout scan of N roots — per-root amortized p99
    "suspended_scan_per_root_p99": 3.0,
    # Dedup check (already_sent + mark_sent) — p99
    "dedup_check_p99": 2.0,
    # Full end-to-end: goal → breach → intent → dedup → dispatch — p99
    "e2e_single_goal_p99": 10.0,
    # Full end-to-end batch of 50 goals — total wall-clock p99
    "e2e_batch_50_total_p99": 100.0,
}


# ──────────────────────────────────────────────────────────────────────────
# Result dataclasses
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class SLOCheck:
    """One SLO threshold check result."""

    slo_name: str
    threshold_ms: float
    actual_p99_ms: float
    passed: bool
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "slo_name": self.slo_name,
            "threshold_ms": self.threshold_ms,
            "actual_p99_ms": round(self.actual_p99_ms, 4),
            "passed": self.passed,
            "sample_count": self.sample_count,
        }


@dataclass
class ScenarioBenchmarkResult:
    """Latency result for one alert scenario across N iterations."""

    scenario_id: str
    group: str
    description: str
    pipeline_stage: str  # "sla_scan" | "job_intent" | "suspended_scan" | "e2e"

    latencies_ms: list[float] = field(default_factory=list)
    error: str | None = None

    @property
    def p50_ms(self) -> float:
        return _percentile(self.latencies_ms, 0.50)

    @property
    def p95_ms(self) -> float:
        return _percentile(self.latencies_ms, 0.95)

    @property
    def p99_ms(self) -> float:
        return _percentile(self.latencies_ms, 0.99)

    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "group": self.group,
            "pipeline_stage": self.pipeline_stage,
            "latency_ms": {
                "avg": round(self.avg_ms, 4),
                "p50": round(self.p50_ms, 4),
                "p95": round(self.p95_ms, 4),
                "p99": round(self.p99_ms, 4),
            },
            "sample_count": len(self.latencies_ms),
            "error": self.error,
        }


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


# ──────────────────────────────────────────────────────────────────────────
# Pipeline builders (mirror test_alert_drift_fixtures.py conventions)
# ──────────────────────────────────────────────────────────────────────────


def _build_sla_config(scenario) -> Any:
    """Build a SlaConfig from the scenario's sla_config_kwargs."""
    from soothe.config.models import SlaConfig

    base = SlaConfig(
        enabled=True,
        warning_seconds=3600,
        critical_seconds=7200,
        breach_seconds=14400,
    )
    return base.model_copy(update=scenario.sla_config_kwargs)


def _build_notify_config(scenario, *, sla: Any | None = None) -> Any:
    """Build an AutopilotNotifyConfig from the scenario's notify_config_kwargs."""
    from soothe.config.models import (
        AutopilotNotifyConfig,
        NotifyEventsConfig,
        NotifyTargetConfig,
    )

    base = AutopilotNotifyConfig(
        enabled=True,
        events=NotifyEventsConfig(),
        targets=[NotifyTargetConfig(kind="email", to_address="ops@example.com")],
        sla=sla or _build_sla_config(scenario),
    )
    return base.model_copy(update=scenario.notify_config_kwargs)


def _build_goal(scenario) -> Any:
    """Build a GoalNode from the scenario's goal_kwargs."""

    from fixtures.alert_scenarios import REF_NOW
    from soothe.context.models import GoalNode

    kwargs = dict(scenario.goal_kwargs)
    if kwargs.get("started_at") is None and "created_at" not in kwargs:
        kwargs["created_at"] = REF_NOW - timedelta(hours=1, minutes=30)
    return GoalNode(**kwargs)


def _make_router(scenario) -> tuple[Any, list]:
    """Build a NotificationRouter with a capturing dispatch_fn.

    Returns (router, seen_list).
    """
    from soothe_autopilot.notify import NotificationRouter, NotifyIntent

    seen: list[NotifyIntent] = []

    async def _dispatch(intent: NotifyIntent) -> None:
        seen.append(intent)

    cfg = _build_notify_config(scenario)
    router = NotificationRouter(cfg, dispatch_fn=_dispatch)
    return router, seen


# ──────────────────────────────────────────────────────────────────────────
# Benchmark runners
# ──────────────────────────────────────────────────────────────────────────


async def _bench_sla_scan_single(scenario, iterations: int) -> ScenarioBenchmarkResult:
    """Benchmark SlaMonitor.scan([single_goal]) → emit_sla_overdue."""
    from soothe_autopilot.sla import SlaMonitor

    goal = _build_goal(scenario)
    now = scenario.now_override

    latencies: list[float] = []
    for _ in range(iterations):
        # New router each iteration to avoid dedup accumulation skewing latency
        router_fresh, _ = _make_router(scenario)
        monitor_fresh = SlaMonitor(_build_sla_config(scenario), router_fresh)
        t0 = time.perf_counter()
        await monitor_fresh.scan([goal], now=now)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    return ScenarioBenchmarkResult(
        scenario_id=scenario.id,
        group=scenario.group,
        description=scenario.description,
        pipeline_stage="sla_scan_single_goal",
        latencies_ms=latencies,
    )


async def _bench_job_intent_emit(scenario, iterations: int) -> ScenarioBenchmarkResult:
    """Benchmark NotificationRouter.emit_job_intent for completed/failed."""
    from soothe_autopilot.notify import NotifyKind

    kind: NotifyKind = "job.failed" if scenario.expected_kind == "job.failed" else "job.completed"
    progress = scenario.progress

    latencies: list[float] = []
    for _ in range(iterations):
        router_fresh, _ = _make_router(scenario)
        goal_fresh = _build_goal(scenario)
        t0 = time.perf_counter()
        await router_fresh.emit_job_intent(kind, goal_fresh, progress=progress)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    return ScenarioBenchmarkResult(
        scenario_id=scenario.id,
        group=scenario.group,
        description=scenario.description,
        pipeline_stage="job_intent_emit",
        latencies_ms=latencies,
    )


async def _bench_suspended_scan(scenario, iterations: int) -> ScenarioBenchmarkResult:
    """Benchmark NotificationRouter.scan_suspended_timeouts([root])."""
    now = scenario.now_override

    latencies: list[float] = []
    for _ in range(iterations):
        router_fresh, _ = _make_router(scenario)
        goal_fresh = _build_goal(scenario)
        t0 = time.perf_counter()
        await router_fresh.scan_suspended_timeouts([goal_fresh], now=now)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    return ScenarioBenchmarkResult(
        scenario_id=scenario.id,
        group=scenario.group,
        description=scenario.description,
        pipeline_stage="suspended_scan",
        latencies_ms=latencies,
    )


async def _bench_e2e_single_goal(scenario, iterations: int) -> ScenarioBenchmarkResult:
    """Benchmark full end-to-end: goal → SLA scan → intent → dedup → dispatch."""
    from soothe_autopilot.sla import SlaMonitor

    latencies: list[float] = []
    for _ in range(iterations):
        router_fresh, seen = _make_router(scenario)
        monitor_fresh = SlaMonitor(_build_sla_config(scenario), router_fresh)
        goal_fresh = _build_goal(scenario)
        now = scenario.now_override

        t0 = time.perf_counter()
        result = await monitor_fresh.scan([goal_fresh], now=now)
        # The scan internally calls router.emit_sla_overdue which does dedup + dispatch
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
        # Touch seen to prevent optimization
        _ = len(seen)
        _ = result

    return ScenarioBenchmarkResult(
        scenario_id=scenario.id,
        group=scenario.group,
        description=scenario.description,
        pipeline_stage="e2e_single_goal",
        latencies_ms=latencies,
    )


async def _bench_dedup_check(scenario, iterations: int) -> ScenarioBenchmarkResult:
    """Benchmark dedup already_sent + mark_sent cycle."""
    from soothe_autopilot.notify.dedup import NotifyDedupStore

    store = NotifyDedupStore(ttl_seconds=86400)

    latencies: list[float] = []
    for i in range(iterations):
        test_key = f"bench:{scenario.id}:{i}"
        t0 = time.perf_counter()
        already = await store.already_sent(test_key)
        if not already:
            await store.mark_sent(test_key)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    return ScenarioBenchmarkResult(
        scenario_id=scenario.id,
        group=scenario.group,
        description=scenario.description,
        pipeline_stage="dedup_check",
        latencies_ms=latencies,
    )


async def _bench_e2e_batch_50(scenarios, iterations: int) -> ScenarioBenchmarkResult:
    """Benchmark full end-to-end SLA scan of 50 goals (batch)."""
    from soothe_autopilot.sla import SlaMonitor

    # Build 50 goals from available scenarios (cycle if fewer than 50).
    # Filter out CFG scenarios (intentionally invalid configs that raise
    # ValidationError) and no-breach scenarios (no goal to scan).
    valid_scenarios = [s for s in scenarios if s.group != "CFG" and s.goal_kwargs]
    if not valid_scenarios:
        valid_scenarios = [s for s in scenarios if s.goal_kwargs]
    goals: list[Any] = []
    routers: list[Any] = []
    sla_configs: list[Any] = []
    for i in range(50):
        scenario = valid_scenarios[i % len(valid_scenarios)]
        router, _ = _make_router(scenario)
        goals.append(_build_goal(scenario))
        routers.append(router)
        sla_configs.append(_build_sla_config(scenario))

    now = valid_scenarios[0].now_override or datetime.now(UTC)

    latencies: list[float] = []
    for _ in range(iterations):
        # Fresh routers to avoid dedup accumulation
        fresh_routers: list[Any] = []
        for i in range(50):
            r, _ = _make_router(valid_scenarios[i % len(valid_scenarios)])
            fresh_routers.append(r)

        # Use the first router's config for a single monitor scan of all goals
        # (realistic: one monitor scans the full DAG)
        monitor = SlaMonitor(sla_configs[0], fresh_routers[0])
        t0 = time.perf_counter()
        await monitor.scan(goals, now=now)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    return ScenarioBenchmarkResult(
        scenario_id="batch_50_mixed",
        group="BATCH",
        description="End-to-end SLA scan of 50 mixed goals",
        pipeline_stage="e2e_batch_50",
        latencies_ms=latencies,
    )


# ──────────────────────────────────────────────────────────────────────────
# SLO evaluation
# ──────────────────────────────────────────────────────────────────────────


def _evaluate_slos(
    results: list[ScenarioBenchmarkResult],
) -> list[SLOCheck]:
    """Map benchmark results to SLO threshold checks."""
    checks: list[SLOCheck] = []

    # Group results by pipeline stage
    by_stage: dict[str, list[ScenarioBenchmarkResult]] = {}
    for r in results:
        by_stage.setdefault(r.pipeline_stage, []).append(r)

    # SLO: sla_scan_single_goal_p99
    sla_single = by_stage.get("sla_scan_single_goal", [])
    if sla_single:
        all_p99 = [r.p99_ms for r in sla_single]
        worst_p99 = max(all_p99)
        checks.append(
            SLOCheck(
                slo_name="sla_scan_single_goal_p99",
                threshold_ms=SLO_THRESHOLDS_MS["sla_scan_single_goal_p99"],
                actual_p99_ms=worst_p99,
                passed=worst_p99 <= SLO_THRESHOLDS_MS["sla_scan_single_goal_p99"],
                sample_count=sum(len(r.latencies_ms) for r in sla_single),
            )
        )

    # SLO: job_intent_emit_p99
    job_intent = by_stage.get("job_intent_emit", [])
    if job_intent:
        all_p99 = [r.p99_ms for r in job_intent]
        worst_p99 = max(all_p99)
        checks.append(
            SLOCheck(
                slo_name="job_intent_emit_p99",
                threshold_ms=SLO_THRESHOLDS_MS["job_intent_emit_p99"],
                actual_p99_ms=worst_p99,
                passed=worst_p99 <= SLO_THRESHOLDS_MS["job_intent_emit_p99"],
                sample_count=sum(len(r.latencies_ms) for r in job_intent),
            )
        )

    # SLO: suspended_scan_per_root_p99
    suspended = by_stage.get("suspended_scan", [])
    if suspended:
        all_p99 = [r.p99_ms for r in suspended]
        worst_p99 = max(all_p99)
        checks.append(
            SLOCheck(
                slo_name="suspended_scan_per_root_p99",
                threshold_ms=SLO_THRESHOLDS_MS["suspended_scan_per_root_p99"],
                actual_p99_ms=worst_p99,
                passed=worst_p99 <= SLO_THRESHOLDS_MS["suspended_scan_per_root_p99"],
                sample_count=sum(len(r.latencies_ms) for r in suspended),
            )
        )

    # SLO: dedup_check_p99
    dedup = by_stage.get("dedup_check", [])
    if dedup:
        all_p99 = [r.p99_ms for r in dedup]
        worst_p99 = max(all_p99)
        checks.append(
            SLOCheck(
                slo_name="dedup_check_p99",
                threshold_ms=SLO_THRESHOLDS_MS["dedup_check_p99"],
                actual_p99_ms=worst_p99,
                passed=worst_p99 <= SLO_THRESHOLDS_MS["dedup_check_p99"],
                sample_count=sum(len(r.latencies_ms) for r in dedup),
            )
        )

    # SLO: e2e_single_goal_p99
    e2e_single = by_stage.get("e2e_single_goal", [])
    if e2e_single:
        all_p99 = [r.p99_ms for r in e2e_single]
        worst_p99 = max(all_p99)
        checks.append(
            SLOCheck(
                slo_name="e2e_single_goal_p99",
                threshold_ms=SLO_THRESHOLDS_MS["e2e_single_goal_p99"],
                actual_p99_ms=worst_p99,
                passed=worst_p99 <= SLO_THRESHOLDS_MS["e2e_single_goal_p99"],
                sample_count=sum(len(r.latencies_ms) for r in e2e_single),
            )
        )

    # SLO: e2e_batch_50_total_p99
    e2e_batch = by_stage.get("e2e_batch_50", [])
    if e2e_batch:
        batch_p99 = e2e_batch[0].p99_ms
        checks.append(
            SLOCheck(
                slo_name="e2e_batch_50_total_p99",
                threshold_ms=SLO_THRESHOLDS_MS["e2e_batch_50_total_p99"],
                actual_p99_ms=batch_p99,
                passed=batch_p99 <= SLO_THRESHOLDS_MS["e2e_batch_50_total_p99"],
                sample_count=len(e2e_batch[0].latencies_ms),
            )
        )

    # SLO: sla_scan_batch_per_goal_p99 (derived from batch)
    if e2e_batch:
        per_goal_p99 = e2e_batch[0].p99_ms / 50.0
        checks.append(
            SLOCheck(
                slo_name="sla_scan_batch_per_goal_p99",
                threshold_ms=SLO_THRESHOLDS_MS["sla_scan_batch_per_goal_p99"],
                actual_p99_ms=per_goal_p99,
                passed=per_goal_p99 <= SLO_THRESHOLDS_MS["sla_scan_batch_per_goal_p99"],
                sample_count=len(e2e_batch[0].latencies_ms),
            )
        )

    return checks


# ──────────────────────────────────────────────────────────────────────────
# Report generation
# ──────────────────────────────────────────────────────────────────────────


def generate_json_report(
    results: list[ScenarioBenchmarkResult],
    slo_checks: list[SLOCheck],
    iterations: int,
) -> str:
    """Generate JSON report."""
    report = {
        "benchmark": "alert_pipeline_latency_slo",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "iterations_per_scenario": iterations,
        "slo_thresholds_ms": SLO_THRESHOLDS_MS,
        "results": [r.to_dict() for r in results],
        "slo_checks": [c.to_dict() for c in slo_checks],
        "all_slos_passed": all(c.passed for c in slo_checks),
    }
    return json.dumps(report, indent=2)


def generate_markdown_report(
    results: list[ScenarioBenchmarkResult],
    slo_checks: list[SLOCheck],
    iterations: int,
) -> str:
    """Generate Markdown report."""
    all_passed = all(c.passed for c in slo_checks)
    status_icon = "✅" if all_passed else "❌"

    lines = [
        f"# Alert Pipeline Latency & SLO Benchmark Report {status_icon}",
        "",
        f"**Timestamp**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Iterations per scenario**: {iterations}",
        f"**All SLOs passed**: {all_passed}",
        "",
        "## SLO Thresholds (ms)",
        "",
        "| SLO Name | Threshold (ms) | Actual p99 (ms) | Passed | Samples |",
        "|----------|----------------|------------------|--------|---------|",
    ]

    for c in slo_checks:
        icon = "✅" if c.passed else "❌"
        lines.append(
            f"| `{c.slo_name}` | {c.threshold_ms:.1f} | {c.actual_p99_ms:.4f} | "
            f"{icon} | {c.sample_count} |"
        )

    lines.append("")

    # Per-scenario latency table
    lines.extend(
        [
            "## Per-Scenario Latency (ms)",
            "",
            "| Scenario | Group | Stage | Avg | p50 | p95 | p99 | Samples |",
            "|----------|-------|-------|-----|-----|-----|-----|---------|",
        ]
    )

    for r in results:
        lines.append(
            f"| {r.scenario_id} | {r.group} | {r.pipeline_stage} | "
            f"{r.avg_ms:.4f} | {r.p50_ms:.4f} | {r.p95_ms:.4f} | {r.p99_ms:.4f} | "
            f"{len(r.latencies_ms)} |"
        )

    lines.append("")

    # SLO threshold reference
    lines.extend(
        [
            "## SLO Threshold Reference",
            "",
            "All thresholds are wall-clock milliseconds for a single end-to-end",
            "pipeline traversal. The pipeline is pure Python (no LLM, no network),",
            "so these budgets leave headroom for CI runner variance and GC pauses.",
            "",
            "| SLO | Threshold | Rationale |",
            "|-----|-----------|-----------|",
            "| `sla_scan_single_goal_p99` | 5.0 ms | SLA monitor scans one goal, classifies tier, builds breach, emits intent. |",
            "| `sla_scan_batch_per_goal_p99` | 2.0 ms | Amortized per-goal in a 50-goal batch (shared scan loop overhead). |",
            "| `job_intent_emit_p99` | 5.0 ms | Router builds intent, checks dedup, dispatches. |",
            "| `suspended_scan_per_root_p99` | 3.0 ms | Per-root in suspended-timeout scan loop. |",
            "| `dedup_check_p99` | 2.0 ms | already_sent + mark_sent on in-memory store. |",
            "| `e2e_single_goal_p99` | 10.0 ms | Full chain: goal → breach → intent → dedup → dispatch. |",
            "| `e2e_batch_50_total_p99` | 100.0 ms | 50-goal batch end-to-end (2 ms/goal budget). |",
            "",
        ]
    )

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────


async def main_async(args: argparse.Namespace) -> int:
    """Run the alert pipeline benchmark and SLO checks.

    Returns exit code: 0 if all SLOs pass, 1 if any SLO is breached.
    """
    from fixtures.alert_scenarios import ALL_ALERT_SCENARIOS

    iterations = args.iterations
    results: list[ScenarioBenchmarkResult] = []

    logger.info(
        "Running alert pipeline benchmark: %d scenarios × %d iterations",
        len(ALL_ALERT_SCENARIOS),
        iterations,
    )

    # Select scenarios for each pipeline stage
    sla_scenarios = [
        s for s in ALL_ALERT_SCENARIOS if s.group == "SLA" and s.expected_kind == "sla.overdue"
    ]
    job_scenarios = [
        s
        for s in ALL_ALERT_SCENARIOS
        if s.group == "JOB" and s.expected_kind in ("job.completed", "job.failed")
    ]
    suspended_scenarios = [
        s
        for s in ALL_ALERT_SCENARIOS
        if s.group == "JOB" and s.expected_kind == "job.suspended_timeout"
    ]
    dedup_scenarios = [s for s in ALL_ALERT_SCENARIOS if s.group == "DEDUP"]

    # Run SLA scan benchmarks
    for scenario in sla_scenarios:
        logger.info("  SLA scan: %s", scenario.id)
        result = await _bench_sla_scan_single(scenario, iterations)
        results.append(result)

    # Run job intent emit benchmarks
    for scenario in job_scenarios:
        logger.info("  Job intent: %s", scenario.id)
        result = await _bench_job_intent_emit(scenario, iterations)
        results.append(result)

    # Run suspended scan benchmarks
    for scenario in suspended_scenarios:
        logger.info("  Suspended scan: %s", scenario.id)
        result = await _bench_suspended_scan(scenario, iterations)
        results.append(result)

    # Run dedup benchmarks
    for scenario in dedup_scenarios:
        logger.info("  Dedup: %s", scenario.id)
        result = await _bench_dedup_check(scenario, iterations)
        results.append(result)

    # Run E2E single-goal benchmarks (use SLA scenarios that produce breaches)
    e2e_scenarios = [
        s for s in ALL_ALERT_SCENARIOS if s.group == "SLA" and s.expected_kind == "sla.overdue"
    ]
    for scenario in e2e_scenarios:
        logger.info("  E2E single: %s", scenario.id)
        result = await _bench_e2e_single_goal(scenario, iterations)
        results.append(result)

    # Run E2E batch-50 benchmark
    logger.info("  E2E batch-50")
    batch_result = await _bench_e2e_batch_50(ALL_ALERT_SCENARIOS, iterations)
    results.append(batch_result)

    # Evaluate SLOs
    slo_checks = _evaluate_slos(results)

    # Generate report
    if args.output == "json":
        report = generate_json_report(results, slo_checks, iterations)
    else:
        report = generate_markdown_report(results, slo_checks, iterations)
    print(report)

    if args.output_file:
        Path(args.output_file).write_text(report)
        logger.info("Report saved to %s", args.output_file)

    # SLO-only mode: exit non-zero if any SLO breached
    if args.slo_only:
        failed = [c for c in slo_checks if not c.passed]
        if failed:
            logger.error("SLO breaches detected:")
            for c in failed:
                logger.error(
                    "  %s: actual=%.4fms > threshold=%.1fms",
                    c.slo_name,
                    c.actual_p99_ms,
                    c.threshold_ms,
                )
            return 1
        logger.info("All SLOs passed")
        return 0

    return 0


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Alert Pipeline Performance Benchmark & Latency SLO Checks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--output",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    parser.add_argument(
        "--output-file",
        help="Save report to file",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=200,
        help="Iterations per scenario for latency measurement (default: 200)",
    )

    parser.add_argument(
        "--slo-only",
        action="store_true",
        help="Exit non-zero if any SLO threshold is breached",
    )

    args = parser.parse_args()

    exit_code = asyncio.run(main_async(args))
    if exit_code != 0:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
