"""Synthetic alert drift test fixtures — one scenario per cataloged alert case.

Cataloged alert scenarios (from the alert scenario catalog) are enumerated
as ``AlertScenario`` dataclasses with synthetic goal/config/progress payloads
and expected outcomes. Each scenario is designed to exercise a specific drift
or escalation path in the SLA monitor and notification router.

This module uses raw dicts and minimal soothe type construction to avoid
circular imports, mirroring the convention in
``packages/soothe/tests/fixtures/plan_benchmark_tasks.py``.

Scenario groups:
    SLA_*  — SLA monitor tiered escalation (sla.overdue)
    JOB_*  — job lifecycle notify (job.completed / job.failed / job.suspended_timeout)
    DEDUP_* — dedup / TTL re-notification behavior
    CFG_*  — config validation (tier ordering, zero thresholds)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# ──────────────────────────────────────────────────────────────────────────
# Scenario dataclass
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class AlertScenario:
    """One synthetic alert scenario with expected outcome.

    Attributes:
        id: Unique scenario identifier (matches catalog entry name).
        group: Scenario group (SLA / JOB / DEDUP / CFG).
        description: Human-readable description of the drift being exercised.
        goal_kwargs: kwargs for ``GoalNode`` construction (status, timestamps,
            maturity, last_gap_analysis, parent_id, etc.).
        sla_config_kwargs: kwargs for ``SlaConfig`` (warning/critical/breach seconds).
        notify_config_kwargs: kwargs for ``AutopilotNotifyConfig`` overrides
            (suspend_after_seconds, suspend_escalation_multiplier, dedup_ttl_seconds,
            enabled, events).
        progress: Optional progress dict for job.completed drift scenarios.
        now_override: Optional fixed clock for deterministic elapsed/age calc.
        expected_kind: Expected ``NotifyKind`` emitted (or None when no alert).
        expected_tier: Expected ``SlaTier`` for SLA scenarios (or None).
        expected_severity: Expected ``Severity`` of the emitted intent (or None).
        expected_no_breach: True when the scenario expects zero breaches/intents.
        expected_intent_count: Expected number of emitted intents after scan.
        expected_skipped: Expected intents suppressed by dedup.
        notes: Implementation notes / drift signal being tested.
    """

    id: str
    group: str
    description: str
    goal_kwargs: dict[str, Any] = field(default_factory=dict)
    sla_config_kwargs: dict[str, Any] = field(default_factory=dict)
    notify_config_kwargs: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] | None = None
    now_override: datetime | None = None
    expected_kind: str | None = None
    expected_tier: str | None = None
    expected_severity: str | None = None
    expected_no_breach: bool = False
    expected_intent_count: int = 0
    expected_skipped: int = 0
    notes: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Shared synthetic builders
# ──────────────────────────────────────────────────────────────────────────

# Fixed reference clock so elapsed/age calculations are deterministic across
# CI runs. All scenarios that need a clock use this as the "now" value.
REF_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)


def _gap_analysis(
    *,
    remaining_gaps: list[str] | None = None,
    distance: str = "moderate",
    components: list[dict] | None = None,
) -> dict:
    """Build a synthetic last_gap_analysis dict (mirrors monitor._extract_gap_items)."""
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


def _progress(
    *,
    total: int = 3,
    completed: int = 3,
    failed: int = 0,
    active: int = 0,
    pending: int = 0,
    suspended: int = 0,
    cancelled: int = 0,
) -> dict:
    """Build a synthetic progress dict for job.completed drift scenarios."""
    pct = int((completed / total) * 100) if total > 0 else 0
    return {
        "total_goals": total,
        "completed_goals": completed,
        "failed_goals": failed,
        "active_goals": active,
        "pending_goals": pending,
        "suspended_goals": suspended,
        "cancelled_goals": cancelled,
        "pct_complete": pct,
        "highlights": [],
        "highlights_omitted": 0,
    }


# ──────────────────────────────────────────────────────────────────────────
# SLA monitor scenarios (sla.overdue tiered escalation)
# ──────────────────────────────────────────────────────────────────────────

SLA_NO_GAPS_NO_BREACH = AlertScenario(
    id="sla_no_gaps_no_breach",
    group="SLA",
    description="Active goal with no gap analysis present → no breach.",
    goal_kwargs={
        "id": "sla-goal-001",
        "description": "Ship feature X",
        "status": "active",
        "started_at": REF_NOW - timedelta(hours=2),
        "last_gap_analysis": None,
    },
    now_override=REF_NOW,
    expected_no_breach=True,
    expected_intent_count=0,
    notes="No last_gap_analysis → _extract_gap_items returns empty → not overdue.",
)

SLA_DISABLED_NO_SCAN = AlertScenario(
    id="sla_disabled_no_scan",
    group="SLA",
    description="SLA monitor disabled → scan returns empty result.",
    goal_kwargs={
        "id": "sla-goal-002",
        "description": "Ship feature Y",
        "status": "active",
        "started_at": REF_NOW - timedelta(hours=3),
        "last_gap_analysis": _gap_analysis(),
    },
    sla_config_kwargs={"enabled": False},
    now_override=REF_NOW,
    expected_no_breach=True,
    expected_intent_count=0,
    notes="config.enabled=False → SlaMonitor.scan returns empty SlaMonitorResult.",
)

SLA_WARNING_TIER = AlertScenario(
    id="sla_warning_tier",
    group="SLA",
    description="Active 1.5h with gaps → WARNING tier (1h < elapsed < 2h).",
    goal_kwargs={
        "id": "sla-goal-003",
        "description": "Ship feature Z",
        "status": "active",
        "started_at": REF_NOW - timedelta(hours=1, minutes=30),
        "last_gap_analysis": _gap_analysis(),
    },
    now_override=REF_NOW,
    expected_kind="sla.overdue",
    expected_tier="warning",
    expected_severity="warning",
    expected_intent_count=1,
    notes="elapsed=5400s >= warning_seconds=3600s but < critical_seconds=7200s.",
)

SLA_CRITICAL_TIER = AlertScenario(
    id="sla_critical_tier",
    group="SLA",
    description="Active 3h with gaps → CRITICAL tier (2h <= elapsed < 4h).",
    goal_kwargs={
        "id": "sla-goal-004",
        "description": "Ship feature W",
        "status": "active",
        "started_at": REF_NOW - timedelta(hours=3),
        "last_gap_analysis": _gap_analysis(),
    },
    now_override=REF_NOW,
    expected_kind="sla.overdue",
    expected_tier="critical",
    expected_severity="error",
    expected_intent_count=1,
    notes="elapsed=10800s >= critical_seconds=7200s but < breach_seconds=14400s.",
)

SLA_BREACH_TIER = AlertScenario(
    id="sla_breach_tier",
    group="SLA",
    description="Active 5h with gaps → BREACH tier (elapsed >= 4h).",
    goal_kwargs={
        "id": "sla-goal-005",
        "description": "Ship feature V",
        "status": "active",
        "started_at": REF_NOW - timedelta(hours=5),
        "last_gap_analysis": _gap_analysis(),
    },
    now_override=REF_NOW,
    expected_kind="sla.overdue",
    expected_tier="breach",
    expected_severity="error",
    expected_intent_count=1,
    notes="elapsed=18000s >= breach_seconds=14400s.",
)

SLA_BELOW_THRESHOLD_NO_BREACH = AlertScenario(
    id="sla_below_threshold_no_breach",
    group="SLA",
    description="Active 30min with gaps → below warning threshold, no breach.",
    goal_kwargs={
        "id": "sla-goal-006",
        "description": "Ship feature U",
        "status": "active",
        "started_at": REF_NOW - timedelta(minutes=30),
        "last_gap_analysis": _gap_analysis(),
    },
    now_override=REF_NOW,
    expected_no_breach=True,
    expected_intent_count=0,
    notes="elapsed=1800s < warning_seconds=3600s → _classify_tier returns None.",
)

SLA_TERMINAL_GOALS_SKIPPED = AlertScenario(
    id="sla_terminal_goals_skipped",
    group="SLA",
    description="Completed/failed goals are skipped (not in _ACTIVE_STATUSES).",
    goal_kwargs={
        "id": "sla-goal-007",
        "description": "Ship feature T",
        "status": "completed",
        "started_at": REF_NOW - timedelta(hours=5),
        "last_gap_analysis": _gap_analysis(),
    },
    now_override=REF_NOW,
    expected_no_breach=True,
    expected_intent_count=0,
    notes="status='completed' not in _ACTIVE_STATUSES → skip.",
)

SLA_DEDUP_SAME_TIER = AlertScenario(
    id="sla_dedup_same_tier",
    group="SLA",
    description="Same goal+tier re-scan → dedup suppresses second alert.",
    goal_kwargs={
        "id": "sla-goal-008",
        "description": "Ship feature S",
        "status": "active",
        "started_at": REF_NOW - timedelta(hours=3),
        "last_gap_analysis": _gap_analysis(),
    },
    now_override=REF_NOW,
    expected_kind="sla.overdue",
    expected_tier="critical",
    expected_severity="error",
    expected_intent_count=1,
    expected_skipped=1,
    notes="Two scans of same goal+tier → first emits, second deduped. Dedup key = goal_id:tier.",
)

SLA_SUSPENDED_GOAL_WITH_GAPS = AlertScenario(
    id="sla_suspended_goal_with_gaps",
    group="SLA",
    description="Suspended goal with gaps still monitored (suspended is active).",
    goal_kwargs={
        "id": "sla-goal-009",
        "description": "Ship feature R",
        "status": "suspended",
        "started_at": REF_NOW - timedelta(hours=2),
        "last_gap_analysis": _gap_analysis(),
    },
    now_override=REF_NOW,
    expected_kind="sla.overdue",
    expected_tier="critical",
    expected_severity="error",
    expected_intent_count=1,
    notes="status='suspended' is in _ACTIVE_STATUSES → eligible for SLA scan.",
)

SLA_CREATED_AT_FALLBACK = AlertScenario(
    id="sla_created_at_fallback",
    group="SLA",
    description="No started_at → uses created_at for elapsed calc.",
    goal_kwargs={
        "id": "sla-goal-010",
        "description": "Ship feature Q",
        "status": "pending",
        "started_at": None,
        # Explicit created_at so elapsed is deterministic (1.5h → WARNING tier:
        # >= 3600s warning threshold, < 7200s critical threshold).
        "created_at": REF_NOW - timedelta(hours=1, minutes=30),
        "last_gap_analysis": _gap_analysis(),
    },
    now_override=REF_NOW,
    expected_kind="sla.overdue",
    expected_tier="warning",
    expected_severity="warning",
    expected_intent_count=1,
    notes="started_at=None → _goal_elapsed_seconds falls back to created_at. "
    "created_at set to 1.5h ago so elapsed=5400s lands in WARNING tier "
    "(>=3600s, <7200s).",
)

# ──────────────────────────────────────────────────────────────────────────
# Job lifecycle notify scenarios (drift-aware severity)
# ──────────────────────────────────────────────────────────────────────────

JOB_COMPLETED_CLEAN_INFO = AlertScenario(
    id="job_completed_clean_info",
    group="JOB",
    description="Completed root, no failed/active children → info severity.",
    goal_kwargs={
        "id": "job-root-001",
        "description": "clean completion",
        "status": "completed",
    },
    progress=_progress(total=2, completed=2),
    expected_kind="job.completed",
    expected_severity="info",
    expected_intent_count=1,
    notes="Baseline: completed root with failed_goals=0, active_goals=0.",
)

JOB_COMPLETED_WITH_FAILED_CHILDREN_WARNING = AlertScenario(
    id="job_completed_with_failed_children_warning",
    group="JOB",
    description="Completed root but children failed → warning (completion drift).",
    goal_kwargs={
        "id": "job-root-002",
        "description": "drift completion",
        "status": "completed",
    },
    progress=_progress(total=3, completed=1, failed=1, active=1),
    expected_kind="job.completed",
    expected_severity="warning",
    expected_intent_count=1,
    notes="Drift signal: failed_goals>0 or active_goals>0 → escalate info→warning.",
)

JOB_COMPLETED_MATURITY_BLOCKERS_WARNING = AlertScenario(
    id="job_completed_maturity_blockers_warning",
    group="JOB",
    description="Completed root with maturity blockers → warning (acceptance drift).",
    goal_kwargs={
        "id": "job-root-003",
        "description": "blocked completion",
        "status": "completed",
        "maturity": {"level": "partial", "blockers": ["verify failed"]},
    },
    expected_kind="job.completed",
    expected_severity="warning",
    expected_intent_count=1,
    notes="Drift signal: maturity.blockers present → escalate info→warning.",
)

JOB_COMPLETED_ACCEPTANCE_NOT_MET_WARNING = AlertScenario(
    id="job_completed_acceptance_not_met_warning",
    group="JOB",
    description="Completed root with acceptance_met=False → warning.",
    goal_kwargs={
        "id": "job-root-004",
        "description": "not accepted",
        "status": "completed",
        "maturity": {"acceptance_met": False},
    },
    expected_kind="job.completed",
    expected_severity="warning",
    expected_intent_count=1,
    notes="Drift signal: maturity.acceptance_met is False → escalate info→warning.",
)

JOB_FAILED_ERROR = AlertScenario(
    id="job_failed_error",
    group="JOB",
    description="Failed root is always error severity.",
    goal_kwargs={
        "id": "job-root-005",
        "description": "boom",
        "status": "failed",
        "error": "crash",
    },
    expected_kind="job.failed",
    expected_severity="error",
    expected_intent_count=1,
    notes="Baseline: job.failed → Severity.ERROR unconditionally.",
)

JOB_SUSPENDED_TIMEOUT_WARNING = AlertScenario(
    id="job_suspended_timeout_warning",
    group="JOB",
    description="Suspended timeout just past threshold → warning.",
    goal_kwargs={
        "id": "job-root-006",
        "description": "paused",
        "status": "suspended",
        "suspended_at": REF_NOW - timedelta(minutes=2),
        "updated_at": REF_NOW - timedelta(minutes=2),
    },
    notify_config_kwargs={"suspend_after_seconds": 60},
    now_override=REF_NOW,
    expected_kind="job.suspended_timeout",
    expected_severity="warning",
    expected_intent_count=1,
    notes="age=120s, threshold=60s, 2x=120s → 120 not > 120 → warning.",
)

JOB_SUSPENDED_TIMEOUT_FAR_PAST_ERROR = AlertScenario(
    id="job_suspended_timeout_far_past_error",
    group="JOB",
    description="Suspended timeout at >=2x threshold → error (drift past suspend window).",
    goal_kwargs={
        "id": "job-root-007",
        "description": "stuck",
        "status": "suspended",
        "suspended_at": REF_NOW - timedelta(minutes=3),
        "updated_at": REF_NOW - timedelta(minutes=3),
    },
    notify_config_kwargs={"suspend_after_seconds": 60},
    now_override=REF_NOW,
    expected_kind="job.suspended_timeout",
    expected_severity="error",
    expected_intent_count=1,
    notes="age=180s, threshold=60s, 2x=120s → 180 > 120 → error (drift escalation).",
)

JOB_SUSPENDED_CUSTOM_MULTIPLIER_ERROR = AlertScenario(
    id="job_suspended_custom_multiplier_error",
    group="JOB",
    description="Suspended at >=3x threshold with multiplier=3.0 → error.",
    goal_kwargs={
        "id": "job-root-008",
        "description": "stuck-long",
        "status": "suspended",
        "suspended_at": REF_NOW - timedelta(minutes=4),
        "updated_at": REF_NOW - timedelta(minutes=4),
    },
    notify_config_kwargs={
        "suspend_after_seconds": 60,
        "suspend_escalation_multiplier": 3.0,
    },
    now_override=REF_NOW,
    expected_kind="job.suspended_timeout",
    expected_severity="error",
    expected_intent_count=1,
    notes="age=240s, threshold=60s, 3x=180s → 240 > 180 → error.",
)

JOB_SUSPENDED_CUSTOM_MULTIPLIER_STILL_WARNING = AlertScenario(
    id="job_suspended_custom_multiplier_still_warning",
    group="JOB",
    description="Suspended between 1x and 3x threshold with multiplier=3.0 → warning.",
    goal_kwargs={
        "id": "job-root-009",
        "description": "stuck-medium",
        "status": "suspended",
        "suspended_at": REF_NOW - timedelta(minutes=2),
        "updated_at": REF_NOW - timedelta(minutes=2),
    },
    notify_config_kwargs={
        "suspend_after_seconds": 60,
        "suspend_escalation_multiplier": 3.0,
    },
    now_override=REF_NOW,
    expected_kind="job.suspended_timeout",
    expected_severity="warning",
    expected_intent_count=1,
    notes="age=120s, threshold=60s, 3x=180s → 120 < 180 → warning.",
)

JOB_CHILD_GOAL_IGNORED = AlertScenario(
    id="job_child_goal_ignored",
    group="JOB",
    description="Child goals (parent_id set) are ignored by router.",
    goal_kwargs={
        "id": "child-001",
        "description": "maker",
        "status": "completed",
        "parent_id": "job-root-100",
    },
    progress=_progress(total=1, completed=1),
    expected_no_breach=True,
    expected_intent_count=0,
    notes="parent_id is not None → emit_job_intent returns None immediately.",
)

JOB_NOTIFY_DISABLED_NOOP = AlertScenario(
    id="job_notify_disabled_noop",
    group="JOB",
    description="Notify config disabled → router is a no-op.",
    goal_kwargs={
        "id": "job-root-010",
        "description": "x",
        "status": "completed",
    },
    notify_config_kwargs={"enabled": False},
    expected_no_breach=True,
    expected_intent_count=0,
    notes="config.enabled=False → emit_job_intent returns None.",
)

# ──────────────────────────────────────────────────────────────────────────
# Dedup / TTL scenarios
# ──────────────────────────────────────────────────────────────────────────

DEDUP_SAME_INTENT_BLOCKED = AlertScenario(
    id="dedup_same_intent_blocked",
    group="DEDUP",
    description="Same intent emitted twice → second is deduped.",
    goal_kwargs={
        "id": "job-root-020",
        "description": "x",
        "status": "failed",
        "error": "boom",
    },
    expected_kind="job.failed",
    expected_severity="error",
    expected_intent_count=1,
    expected_skipped=1,
    notes="First emit succeeds, second returns None (dedup_key collision).",
)

DEDUP_TTL_ZERO_NO_EXPIRY = AlertScenario(
    id="dedup_ttl_zero_no_expiry",
    group="DEDUP",
    description="TTL=0 means no expiry (keys persist indefinitely).",
    goal_kwargs={
        "id": "job-root-021",
        "description": "ttl-test",
        "status": "failed",
        "error": "boom",
    },
    notify_config_kwargs={"dedup_ttl_seconds": 0},
    expected_kind="job.failed",
    expected_severity="error",
    expected_intent_count=1,
    expected_skipped=1,
    notes="ttl_seconds=0 → _is_expired always False → dedup blocks second emit.",
)

# ──────────────────────────────────────────────────────────────────────────
# Config validation scenarios (no goal, just config construction)
# ──────────────────────────────────────────────────────────────────────────

CFG_CRITICAL_BELOW_WARNING_REJECTED = AlertScenario(
    id="cfg_critical_below_warning_rejected",
    group="CFG",
    description="SlaConfig with critical < warning → ValueError.",
    sla_config_kwargs={
        "enabled": True,
        "warning_seconds": 3600,
        "critical_seconds": 1800,
    },
    expected_no_breach=True,
    expected_intent_count=0,
    notes="model_validator rejects critical_seconds < warning_seconds.",
)

CFG_BREACH_BELOW_CRITICAL_REJECTED = AlertScenario(
    id="cfg_breach_below_critical_rejected",
    group="CFG",
    description="SlaConfig with breach < critical → ValueError.",
    sla_config_kwargs={
        "enabled": True,
        "critical_seconds": 7200,
        "breach_seconds": 3600,
    },
    expected_no_breach=True,
    expected_intent_count=0,
    notes="model_validator rejects breach_seconds < critical_seconds.",
)

CFG_ZERO_THRESHOLDS_DISABLE_TIER = AlertScenario(
    id="cfg_zero_thresholds_disable_tier",
    group="CFG",
    description="Zero thresholds disable that tier (no raise, just no alert).",
    sla_config_kwargs={
        "enabled": True,
        "warning_seconds": 0,
        "critical_seconds": 0,
        "breach_seconds": 0,
    },
    goal_kwargs={
        "id": "sla-goal-cfg",
        "description": "zero tier test",
        "status": "active",
        "started_at": REF_NOW - timedelta(hours=5),
        "last_gap_analysis": _gap_analysis(),
    },
    now_override=REF_NOW,
    expected_no_breach=True,
    expected_intent_count=0,
    notes="All thresholds=0 → _classify_tier returns None for every tier.",
)

# ──────────────────────────────────────────────────────────────────────────
# Master catalog
# ──────────────────────────────────────────────────────────────────────────

# All cataloged alert scenarios, in catalog order.
ALL_ALERT_SCENARIOS: list[AlertScenario] = [
    # SLA monitor tiered escalation
    SLA_NO_GAPS_NO_BREACH,
    SLA_DISABLED_NO_SCAN,
    SLA_WARNING_TIER,
    SLA_CRITICAL_TIER,
    SLA_BREACH_TIER,
    SLA_BELOW_THRESHOLD_NO_BREACH,
    SLA_TERMINAL_GOALS_SKIPPED,
    SLA_DEDUP_SAME_TIER,
    SLA_SUSPENDED_GOAL_WITH_GAPS,
    SLA_CREATED_AT_FALLBACK,
    # Job lifecycle notify (drift-aware severity)
    JOB_COMPLETED_CLEAN_INFO,
    JOB_COMPLETED_WITH_FAILED_CHILDREN_WARNING,
    JOB_COMPLETED_MATURITY_BLOCKERS_WARNING,
    JOB_COMPLETED_ACCEPTANCE_NOT_MET_WARNING,
    JOB_FAILED_ERROR,
    JOB_SUSPENDED_TIMEOUT_WARNING,
    JOB_SUSPENDED_TIMEOUT_FAR_PAST_ERROR,
    JOB_SUSPENDED_CUSTOM_MULTIPLIER_ERROR,
    JOB_SUSPENDED_CUSTOM_MULTIPLIER_STILL_WARNING,
    JOB_CHILD_GOAL_IGNORED,
    JOB_NOTIFY_DISABLED_NOOP,
    # Dedup / TTL
    DEDUP_SAME_INTENT_BLOCKED,
    DEDUP_TTL_ZERO_NO_EXPIRY,
    # Config validation
    CFG_CRITICAL_BELOW_WARNING_REJECTED,
    CFG_BREACH_BELOW_CRITICAL_REJECTED,
    CFG_ZERO_THRESHOLDS_DISABLE_TIER,
]

# Index for quick lookup by scenario id.
SCENARIOS_BY_ID: dict[str, AlertScenario] = {s.id: s for s in ALL_ALERT_SCENARIOS}

# Grouped by group for targeted test runs.
SCENARIOS_BY_GROUP: dict[str, list[AlertScenario]] = {}
for _s in ALL_ALERT_SCENARIOS:
    SCENARIOS_BY_GROUP.setdefault(_s.group, []).append(_s)
