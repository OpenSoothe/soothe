# BM-006: Alert Pipeline Latency & SLO Benchmark

> **Purpose**: Measure end-to-end latency of the alert/drift-detection pipeline and enforce measurable SLO thresholds for each pipeline stage.
>
> **Last Updated**: 2026-08-19
>
> **Status**: Active

---

## Overview

This benchmark evaluates the latency characteristics of the alert pipeline
that detects drift in job-root goals and dispatches notification intents:

1. **SLA monitor scan** — `SlaMonitor.scan([goals])` classifies active goals
   against SLA thresholds and dispatches `sla.overdue` intents.
2. **Job lifecycle intent emit** — `NotificationRouter.emit_job_intent()`
   builds, deduplicates, and dispatches `job.completed` / `job.failed` intents
   with drift-aware severity escalation.
3. **Suspended-timeout scan** — `NotificationRouter.scan_suspended_timeouts()`
   detects roots past their suspend threshold and escalates severity when
   drift past the suspend window is detected.
4. **Dedup check** — `NotifyDedupStore.already_sent()` + `mark_sent()` cycle.
5. **End-to-end** — Full chain: `GoalNode → SlaMonitor.scan → breach →
   NotificationRouter.emit_sla_overdue → NotifyIntent → dedup → dispatch`.

The pipeline is pure Python (no LLM, no network), so latencies are
sub-millisecond. SLO thresholds are generous budgets that leave headroom
for CI runner variance, GC pauses, and future feature additions.

---

## Pipeline Stages & SLO Thresholds

| SLO Name | Threshold (ms) | Pipeline Stage | Rationale |
|----------|----------------|----------------|-----------|
| `sla_scan_single_goal_p99` | 5.0 | SLA scan of one goal: `_extract_gap_items` → `_classify_tier` → `SlaBreach` → `emit_sla_overdue` | Covers gap extraction, tier classification, breach construction, and intent dispatch for a single goal. |
| `sla_scan_batch_per_goal_p99` | 2.0 | Amortized per-goal in a 50-goal batch | Shared scan-loop overhead amortized across goals; catches O(n²) regressions. |
| `job_intent_emit_p99` | 5.0 | `emit_job_intent` (completed/failed): `_severity_for` → `_title_for` → `_body_for` → `NotifyIntent` → dedup → dispatch | Includes drift-aware severity escalation (progress dict, maturity blockers). |
| `suspended_scan_per_root_p99` | 3.0 | `scan_suspended_timeouts` per root: age calc → threshold compare → `emit_job_intent` | Per-root in the scan loop; includes suspend-escalation multiplier check. |
| `dedup_check_p99` | 2.0 | `already_sent` + `mark_sent` on in-memory store | Dedup is on the hot path of every intent emit; must be fast. |
| `e2e_single_goal_p99` | 10.0 | Full chain: goal → breach → intent → dedup → dispatch | End-to-end budget for one goal traversing the entire pipeline. |
| `e2e_batch_50_total_p99` | 100.0 | 50-goal batch SLA scan (total wall-clock) | Realistic watchdog-tick scenario; 2 ms/goal budget. |

---

## Test Cases

### TC-001: SLA Scan Single Goal — WARNING Tier

**Scenario**: `sla_warning_tier` — active goal 1.5h with gaps → WARNING tier.

**Pipeline**: `SlaMonitor.scan([goal], now)` → `emit_sla_overdue` → `NotifyIntent`

**SLO**: p99 ≤ 5.0 ms (`sla_scan_single_goal_p99`)

**Verification Conditions**:
- [ ] p99 latency ≤ 5.0 ms
- [ ] Intent dispatched with `severity=warning`, `tier=warning`
- [ ] 100 iterations measured

---

### TC-002: SLA Scan Single Goal — CRITICAL Tier

**Scenario**: `sla_critical_tier` — active goal 3h with gaps → CRITICAL tier.

**Pipeline**: `SlaMonitor.scan([goal], now)` → `emit_sla_overdue` → `NotifyIntent`

**SLO**: p99 ≤ 5.0 ms (`sla_scan_single_goal_p99`)

**Verification Conditions**:
- [ ] p99 latency ≤ 5.0 ms
- [ ] Intent dispatched with `severity=error`, `tier=critical`
- [ ] 100 iterations measured

---

### TC-003: SLA Scan Single Goal — BREACH Tier

**Scenario**: `sla_breach_tier` — active goal 5h with gaps → BREACH tier.

**Pipeline**: `SlaMonitor.scan([goal], now)` → `emit_sla_overdue` → `NotifyIntent`

**SLO**: p99 ≤ 5.0 ms (`sla_scan_single_goal_p99`)

**Verification Conditions**:
- [ ] p99 latency ≤ 5.0 ms
- [ ] Intent dispatched with `severity=error`, `tier=breach`
- [ ] 100 iterations measured

---

### TC-004: Job Completed Intent Emit — Clean (INFO)

**Scenario**: `job_completed_clean_info` — completed root, no failed children.

**Pipeline**: `emit_job_intent("job.completed", goal, progress)` → `NotifyIntent`

**SLO**: p99 ≤ 5.0 ms (`job_intent_emit_p99`)

**Verification Conditions**:
- [ ] p99 latency ≤ 5.0 ms
- [ ] Intent dispatched with `severity=info`
- [ ] 100 iterations measured

---

### TC-005: Job Completed Intent Emit — Drift (WARNING)

**Scenario**: `job_completed_with_failed_children_warning` — completed root with
failed/active children → drift escalation.

**Pipeline**: `emit_job_intent("job.completed", goal, progress)` → `NotifyIntent`

**SLO**: p99 ≤ 5.0 ms (`job_intent_emit_p99`)

**Verification Conditions**:
- [ ] p99 latency ≤ 5.0 ms
- [ ] Intent dispatched with `severity=warning` (drift escalation)
- [ ] 100 iterations measured

---

### TC-006: Job Failed Intent Emit

**Scenario**: `job_failed_error` — failed root → error severity.

**Pipeline**: `emit_job_intent("job.failed", goal)` → `NotifyIntent`

**SLO**: p99 ≤ 5.0 ms (`job_intent_emit_p99`)

**Verification Conditions**:
- [ ] p99 latency ≤ 5.0 ms
- [ ] Intent dispatched with `severity=error`
- [ ] 100 iterations measured

---

### TC-007: Suspended-Timeout Scan — WARNING

**Scenario**: `job_suspended_timeout_warning` — suspended just past threshold.

**Pipeline**: `scan_suspended_timeouts([root], now)` → `emit_job_intent`

**SLO**: p99 ≤ 3.0 ms (`suspended_scan_per_root_p99`)

**Verification Conditions**:
- [ ] p99 latency ≤ 3.0 ms
- [ ] Intent dispatched with `severity=warning`
- [ ] 100 iterations measured

---

### TC-008: Suspended-Timeout Scan — Drift Escalation (ERROR)

**Scenario**: `job_suspended_timeout_far_past_error` — suspended ≥ 2× threshold
→ drift escalation to error.

**Pipeline**: `scan_suspended_timeouts([root], now)` → `emit_job_intent`

**SLO**: p99 ≤ 3.0 ms (`suspended_scan_per_root_p99`)

**Verification Conditions**:
- [ ] p99 latency ≤ 3.0 ms
- [ ] Intent dispatched with `severity=error` (drift past suspend window)
- [ ] 100 iterations measured

---

### TC-009: Dedup Check Cycle

**Scenario**: In-memory `NotifyDedupStore` with TTL=86400s.

**Pipeline**: `already_sent(key)` → `mark_sent(key)`

**SLO**: p99 ≤ 2.0 ms (`dedup_check_p99`)

**Verification Conditions**:
- [ ] p99 latency ≤ 2.0 ms
- [ ] 100 iterations measured (unique keys per iteration)

---

### TC-010: End-to-End Single Goal

**Scenario**: `sla_warning_tier` — full pipeline traversal.

**Pipeline**: `GoalNode → SlaMonitor.scan → _extract_gap_items →
_classify_tier → SlaBreach → emit_sla_overdue → NotifyIntent → dedup → dispatch`

**SLO**: p99 ≤ 10.0 ms (`e2e_single_goal_p99`)

**Verification Conditions**:
- [ ] p99 latency ≤ 10.0 ms
- [ ] Intent dispatched to the capturing sink
- [ ] 100 iterations measured

---

### TC-011: End-to-End Batch of 50 Goals

**Scenario**: 50 mixed goals (WARNING/CRITICAL/BREACH/suspended/created_at_fallback).

**Pipeline**: `SlaMonitor.scan([50 goals], now)` — realistic watchdog-tick scan.

**SLO**: p99 ≤ 100.0 ms total (`e2e_batch_50_total_p99`)

**Verification Conditions**:
- [ ] p99 total latency ≤ 100.0 ms
- [ ] 100 iterations measured

---

### TC-012: Batch Per-Goal Amortized

**Scenario**: Same 50-goal batch as TC-011.

**Pipeline**: Derived SLO: total batch latency / 50.

**SLO**: p99 ≤ 2.0 ms per goal (`sla_scan_batch_per_goal_p99`)

**Verification Conditions**:
- [ ] Amortized per-goal p99 ≤ 2.0 ms
- [ ] Catches O(n²) regressions in the scan loop
- [ ] 100 iterations measured

---

## Execution Instructions

### Pytest SLO Checks (CI-runnable)

```bash
# Run all SLO checks as part of the unit test suite
uv run pytest packages/soothe-autopilot/tests/unit/core/autopilot/test_alert_pipeline_slo.py -v

# Run a single SLO test
uv run pytest packages/soothe-autopilot/tests/unit/core/autopilot/test_alert_pipeline_slo.py::test_slo_e2e_single_goal_p99 -v
```

### Benchmark Script (full report with JSON/markdown output)

```bash
# Run all scenarios, print markdown report
python scripts/benchmark_alert_pipeline.py

# JSON output
python scripts/benchmark_alert_pipeline.py --output json

# Save report to file
python scripts/benchmark_alert_pipeline.py --output-file report.md

# Scale up iterations for tighter percentile estimates
python scripts/benchmark_alert_pipeline.py --iterations 500

# SLO-only mode (exit non-zero if any SLO breached — for CI gates)
python scripts/benchmark_alert_pipeline.py --slo-only
```

### Test Fixtures

All scenarios come from `packages/soothe-autopilot/tests/fixtures/alert_scenarios.py`
(the same `AlertScenario` catalog used by `test_alert_drift_fixtures.py`).

---

## Success Criteria

| Criterion | Target |
|-----------|--------|
| All SLO thresholds met | ✅ 12/12 test cases pass |
| No SLO regression > 2× threshold | All p99 values < 2× their threshold |
| Batch scalability | 50-goal batch completes in < 100 ms p99 |
| Dedup hot-path performance | < 2.0 ms p99 per dedup cycle |

---

## Status Tracking

| Run | Date | Environment | All SLOs Passed | Worst p99 (ms) | Notes |
|-----|------|-------------|-----------------|----------------|-------|
| 1 | 2026-08-19 | Linux aarch64, Python 3.12 | ⏱️ Pending | — | Initial implementation |

---

## Related Files

| File | Purpose |
|------|---------|
| `scripts/benchmark_alert_pipeline.py` | Full benchmark runner with JSON/markdown reporting and `--slo-only` CI gate |
| `packages/soothe-autopilot/tests/unit/core/autopilot/test_alert_pipeline_slo.py` | Pytest SLO checks (CI-runnable, 12 test cases) |
| `packages/soothe-autopilot/tests/fixtures/alert_scenarios.py` | Shared `AlertScenario` catalog (26 scenarios) |
| `packages/soothe-autopilot/tests/unit/core/autopilot/test_alert_drift_fixtures.py` | Functional correctness tests for the same scenarios |
| `packages/soothe-autopilot/src/soothe_autopilot/sla/monitor.py` | `SlaMonitor.scan` — SLA tier classification and breach detection |
| `packages/soothe-autopilot/src/soothe_autopilot/notify/router.py` | `NotificationRouter` — intent construction, dedup, dispatch |
| `packages/soothe-autopilot/src/soothe_autopilot/notify/dedup.py` | `NotifyDedupStore` — at-most-once delivery keys |
