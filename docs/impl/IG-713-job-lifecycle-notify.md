# IG-713: Job lifecycle notify push (multi-channel)

**Created**: 2026-08-07  
**Status**: Done  
**Related**: [RFC-204](../specs/RFC-204-autopilot-mode.md),
[RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md),
[RFC-228](../specs/RFC-228-autopilot-job-ipc.md),
[RFC-620](../specs/RFC-620-channel-architecture.md)

---

## Goal

Push job-root alerts (`completed`, `failed`, `suspended` past a configurable
age) to users via pluggable **NotifySink** adapters in the daemon. Phase 1:
email (SMTP) + webhook. Same contracts accept Feishu IM and other channels
without host redesign.

## Design rules

1. Host owns channel-agnostic `NotifyIntent` + `NotificationRouter` (dedup,
   event filter). Daemon owns `NotifySink` + `NotifyDispatcher` (I/O).
2. Chat RFC-620 `Channel` stays for conversations; notify does not require
   inbound chat loops. IM sinks may reuse platform send helpers later.
3. Job-root only — never spam on every child goal completion.
   Email/HTML progress uses status counts + capped attention highlights
   (failed/cancelled/active/suspended); never dump the full goal list.
4. Delivery is fail-soft; never blocks Autopilot scheduling.
5. `soothe` must not import `soothe_daemon` — daemon injects `dispatch` callback.

## Extension recipe (new sink)

1. Add `FooNotifySink` under `soothe_daemon/notify/` implementing `NotifySink`.
2. Register in `build_notify_dispatcher(config)`.
3. Add `agent.autopilot.notify.sinks.foo` config (Pydantic + templates).
4. No host / router changes.

## Deliverables

- [x] Host: `NotifyIntent`, `NotificationRouter`, suspend timer, dedup
- [x] Host: compact DAG progress (`build_job_notify_progress`) on intents
- [x] Daemon: `NotifySink`, `NotifyDispatcher`, email + webhook sinks
- [x] Daemon: structured HTML email render (progress bar + highlights)
- [x] Feishu sink stub + config schema (`enabled: false`)
- [x] Config templates synced
- [x] Unit tests + verify

## Non-goals

- Full chat Channel discovery at daemon boot
- Live Feishu production send (stub only in Phase 1)
- IMAP agent turns for alerts
- Dreaming-mode notify spam
- Full per-goal DAG dump in email bodies

## Threshold tuning (production pattern analysis)

Three hardcoded thresholds were promoted to configurable fields based on
production drift alert pattern analysis (GAN-01 through GAN-04). All
defaults preserve prior behavior; operators override via YAML config.

### Tuned fields

| Field | Location | Default | Constraint | Rationale |
|-------|----------|---------|------------|-----------|
| `suspend_escalation_multiplier` | `AutopilotNotifyConfig` | `2.0` | `ge=1.0, le=10.0` | Controls when suspended-timeout escalates from WARNING to ERROR. Default 2.0 means 2× the `suspend_after_seconds` threshold (5400s at default 2700s). Operators can tighten (1.5 = earlier escalation) or loosen (3.0 = more tolerance) based on job-duration distributions. |
| `dedup_ttl_seconds` | `AutopilotNotifyConfig` | `86400` (24h) | `ge=0` | TTL for dedup keys. Keys expire after TTL so long-running jobs can re-notify when state changes past the window. `0` disables expiry (original behavior — keys persist indefinitely). |
| `rate_limit_seconds` | `EmailNotifySinkConfig` | `5.0` | `ge=0.0, le=300.0` | Minimum seconds between email sends to the same recipient (per job+kind+address key). `0` disables rate-limiting. Allows tuning for SMTP provider limits. |

### Config locations (synced per config-sync rule)

- `config/soothe.template.yml` — canonical defaults
- `config/develop/soothe.yml` — dev overrides (multiplier + TTL + rate-limit)
- `packages/soothe-daemon/src/soothe_daemon/setup/templates/soothe.yml` — packaged copy

### Severity classification logic (verified)

`_severity_for()` in `router.py` is purely structural — no keyword/regex
heuristics (per RFC-630). Classification uses:

1. `kind` enum literal (`job.completed` / `job.suspended_timeout` / `job.failed`)
2. `progress` dict counters (`failed_goals`, `active_goals`)
3. `goal.maturity` dict (`blockers`, `acceptance_met`)
4. Arithmetic comparison (`suspended_for_seconds > multiplier × threshold`)

Branch coverage: B1 (info), B2–B4 (warning via progress/maturity drift),
B5 (warning under 2× threshold), B6 (error above 2× threshold), B7
(error unconditional for failed). All verified against GAN-02 scenario
catalog.

### Validation results

- Config field defaults: correct (3/3)
- Config constraints: correct (reject out-of-range, accept edge cases)
- Severity classification: correct (7/7 branches, 3 multiplier values tested)
- Dedup TTL: correct (expiry allows re-notification, `ttl=0` disables)
- Email rate-limit: correct (config value flows to sink)
- YAML sync: correct (3/3 files contain all 3 new fields)
- Python compile: all 4 changed source files pass
