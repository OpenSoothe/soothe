# IG-743: Dynamic Periodic DAG Health LLM

**Created**: 2026-08-14  
**Status**: Implemented  
**Related**: [RFC-625](../specs/RFC-625-autopilot-monitor-context-engine-unification.md)

---

## Goal

Stop burning monitor LLM tokens on idle / empty Autopilot DAGs while keeping
the verification timer for structural deadlock recovery and resource watchdogs.

## Problem

`AutopilotMonitor._verification_loop` called `verify_dag_health` (LLM) every
`verify_interval` seconds whenever Autopilot was running — including empty CE,
all-terminal jobs, and dreaming idle.

## Design

1. **Structural gate** — Call health LLM only when:
   - `verify_llm_enabled` is true
   - Non-terminal goal count ≥ `verify_llm_min_nonterminal`
   - Optional fingerprint debounce: skip LLM when DAG fingerprint unchanged
     since the last LLM health call
2. **Structural-only path** — When gated off: heuristic + IG-697 deadlock
   merge (no LLM); still `apply_health_report`.
3. **Dynamic interval** — `verify_interval` while non-terminal work exists;
   `verify_idle_interval` when DAG empty/complete (`0` = reuse active interval).
4. **Watchdogs unchanged** — Suspend-notify scan and resource reconcile still
   run every tick.

## Config (`agent.autopilot`)

| Field | Default | Meaning |
|-------|---------|---------|
| `verify_interval` | `30` | Tick when non-terminal goals exist |
| `verify_idle_interval` | `300` | Tick when empty/complete (`0` → use `verify_interval`) |
| `verify_llm_enabled` | `true` | Kill-switch for health LLM |
| `verify_llm_min_nonterminal` | `1` | Min non-terminal goals to call LLM |
| `verify_llm_debounce` | `true` | Skip LLM when fingerprint unchanged |

## Acceptance

- [x] Empty / all-terminal DAG does not invoke health LLM
- [x] Non-terminal goals still invoke health LLM (when enabled)
- [x] Debounce skips repeat LLM on unchanged fingerprint
- [x] Idle interval used when DAG complete
- [x] Templates + develop + daemon setup templates synced
- [x] Stale always-on health LLM docs/comments + ig697 LLM-fail shim cleansed
- [x] `./scripts/verify_finally.sh` green
