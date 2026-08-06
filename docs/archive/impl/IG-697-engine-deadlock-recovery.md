# IG-697: Engine-owned DAG deadlock recovery

**Created**: 2026-08-06  
**Status**: Done  
**Related**: [RFC-204](../specs/RFC-204-autopilot-mode.md),
[RFC-625](../specs/RFC-625-autopilot-monitor-context-engine-unification.md),
[IG-678](IG-678-autopilot-ce-rails-production-readiness.md),
[IG-693](IG-693-rail-subgoal-consensus-exhaustion-recovery.md),
[IG-695](IG-695-rail-wave-idle-feedback-deadlock.md)

---

## Goal

Autopilot engine (monitor / DAG health / backoff) must unblock deadlocked
jobs via analyze → recover → continue — not by encoding every failure mode
in LoopRail YAML.

Incident: job `921c6d32` — wave makers completed; integrate `69f7d71c`
failed (consensus thin evidence); backoff attempted `failed → suspended`
(illegal); health LLM suggested reset but apply only reactivates
`suspended`/`blocked`; rail `branch_is_stuck` does not match integrators;
~17k no-op `dag_idle` events.

## Design rules

1. **Rail** = happy-path phase policy (spawn makers, integrate, commit…).
2. **Engine** = liveness backstop when no active work and a failed worker
   blocks pending dependents.
3. Never `suspend` a `failed` goal (CE transition is `failed → pending` only).
4. Never auto-dispatch rail **job roots** as workers.
5. Engine recovery is budgeted (`engine_recovery_count` /
   `max_engine_recoveries`); resets consensus send-back so a retry can
   produce fresh evidence.
6. Failed-goal recovery requires all hard deps **completed** (not merely
   terminal — failed/cancelled deps do not unlock recovery).
7. On retry/recover, prior `goal.error` (+ recovery reason) is appended to
   `guidance_accumulated` so the next worker dispatch receives it as
   `operator_guidance`. Consensus `send_back` likewise appends its reasoning.

## Deliverables

- [x] `GoalNode.engine_recovery_count` + `AutopilotConfig.max_engine_recoveries`
- [x] `ContextEngine.recover_failed_goal` (failed → pending, budgeted)
- [x] Backoff apply: retry or leave failed — never suspend failed
- [x] Health apply: reset/recover failed non-root workers when deps completed
- [x] Structural deadlock detection merged into health suggest_reset
- [x] Prompt constraint update for failed-worker reset
- [x] Failure reason → `guidance_accumulated` on retry / recover / send_back
- [x] Unit tests + `./scripts/verify_finally.sh`

## Out of scope

- New rail YAML verbs for integrate retry
- Domain probes (git/pytest) inside consensus
- Auto-completing rail job roots without maturity / rail phases

## Acceptance

- [x] Failed integrate with completed maker deps + pending root → engine
  recovers integrate to pending within one health cycle
- [x] Exhausted engine recovery budget → leave failed, no illegal transitions
- [x] Rail job roots never force-recovered as workers
- [x] `./scripts/verify_finally.sh` green

**Status**: Done

