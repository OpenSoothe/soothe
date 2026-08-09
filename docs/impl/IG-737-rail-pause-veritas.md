# IG-737: Rail `pause_for_user` → Veritas auto-clarification

**Created**: 2026-08-09  
**Status**: Done  
**Related**: [RFC-231](../specs/RFC-231-looprail-rail-exec.md),
[RFC-622](../specs/RFC-622-clarification-relay.md),
[RFC-623](../specs/RFC-623-veritas-auto-mode-robustness.md),
[IG-707](IG-707-autopilot-automatic-consensus-no-operator-suspend.md)

---

## Goal

Every LoopRail human gate (`then: pause_for_user`) runs Veritas auto-clarification
in autopilot before CE-suspending the job root. High-confidence **PROCEED** skips
suspend and fires `user_intervention` (same rail event as operator resume).
Defer / deny / failure keeps today’s suspend + `job.suspended_timeout` path.

## Behavior matrix

| Veritas outcome | CE root | Rail `suspended` | Rail event |
|-----------------|---------|------------------|------------|
| PROCEED (confidence ≥ min) | unchanged (not suspended) | false | `user_intervention` |
| PAUSE / deny | suspended | true | (none) |
| defer / error / kill-switch / no config | suspended | true | (none) |

Kill-switch: `agent.autopilot.rail_pause_auto_clarify` (default `true`).

Clarification origin: `rail_pause` (not in `force_manual_origins`).

## Deliverables

- [x] `rail_pause` clarification origin
- [x] `pause_clarify` helper + answer vocabulary parse (PROCEED / PAUSE)
- [x] `_do_pause_for_user` clarify-first + audit on `rail_state.json`
- [x] Config + daemon `soothe_config` injection
- [x] Unit tests (proceed / defer / deny / spike auto-proceed)
- [x] Cleanse: drop unused rail package re-exports, getattr shim, stale
  IG-707/RFC-204/spike pause wording; keep fail-open suspend without config
