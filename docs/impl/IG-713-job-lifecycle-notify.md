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
4. Delivery is fail-soft; never blocks Autopilot scheduling.
5. `soothe` must not import `soothe_daemon` — daemon injects `dispatch` callback.

## Extension recipe (new sink)

1. Add `FooNotifySink` under `soothe_daemon/notify/` implementing `NotifySink`.
2. Register in `build_notify_dispatcher(config)`.
3. Add `agent.autopilot.notify.sinks.foo` config (Pydantic + templates).
4. No host / router changes.

## Deliverables

- [x] Host: `NotifyIntent`, `NotificationRouter`, suspend timer, dedup
- [x] Daemon: `NotifySink`, `NotifyDispatcher`, email + webhook sinks
- [x] Feishu sink stub + config schema (`enabled: false`)
- [x] Config templates synced
- [x] Unit tests + verify

## Non-goals

- Full chat Channel discovery at daemon boot
- Live Feishu production send (stub only in Phase 1)
- IMAP agent turns for alerts
- Dreaming-mode notify spam
