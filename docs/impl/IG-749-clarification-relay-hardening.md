# IG-749: Clarification Relay Hardening

## Goal

Make the StrangeLoop clarification relay (RFC-622 / RFC-623) stable under
corner cases: hard-defer must park via Context Engine (resumable), orphaned
resume must fail closed, wire events must carry `defer_kind`, empty answers /
empty `ask_user` must not spin, and Autopilot must not `send_back` over a CE
park.

## In scope

- `soothe.sloop.clarification` package hardening
- `await_user` + `LoopRuntimeContext.park_for_clarification`
- Orphaned interrupt resume in orchestrator runner
- Wire `ClarificationDeferredEvent.defer_kind`
- Executor empty `ask_user` capture failure (no auto-resume spin)
- Autopilot: skip `send_back` when goal is `awaiting_clarification`

## Out of scope

- New CLI `goal answer` UX polish
- Live producers for `plan_generate` / `evaluate` clarification origins
- Autopilot `max_defer_age_hours` sweeper

## Hang semantics

Hard defer ends the graph (`last_outcome=deferred` → `END`). Workers do not
spin. CE `awaiting_clarification` is a blocked park (scheduler skips
`BLOCKED_STATES`), not a hung process.

## Verification

`./scripts/verify_finally.sh`

## Cleanse (same pass)

- Removed dead `LoopRuntimeContext.mark_goal_status` (superseded by
  `park_for_clarification`).
- Collapsed triple hard-defer paths in `await_user` into `_hard_defer`.
- Dropped getattr shim / test-only `mark_goal_status` fallback.
- Trimmed executor one-shot resume flag verbosity; slimmed await tests.
