# IG-693: Rail Subgoal Consensus Exhaustion Recovery

**Created**: 2026-08-05  
**Status**: Done  
**Related**: [RFC-204](../specs/RFC-204-autopilot-mode.md),
[RFC-230](../specs/RFC-230-job-maturity-assessment.md),
[RFC-625](../specs/RFC-625-autopilot-monitor-context-engine-unification.md),
[IG-680](IG-680-autopilot-dag-health-evidence-deps.md),
[IG-687](IG-687-greenfield-system-rail.md),
[IG-692](IG-692-job-maturity-assessment.md),
[IG-697](IG-697-engine-deadlock-recovery.md),
LoopRail design draft

---

## Goal

Stop rail jobs from hanging when a **subgoal** exhausts its consensus
send-back budget, without teaching Autopilot about rail-specific ops
(git commits, cargo, pytest hard-accept).

Incident: job `921c6d32` (`greenfield-system`) — makers `api` / `tests`
reached send_back 3/3 → **suspended**; health correctly refused reset;
rail never saw `goal_failed`; integrate never spawned.

---

## Design rules

1. **Budget is per subgoal**, not the job root.
2. **Autopilot is domain-agnostic**: no git/commit/pytest (or similar)
   hard-accept overrides for rail-bound goals.
3. **Rail-bound exhaustion → `failed` + `goal_failed`** (not silent
   `suspended`).
4. **LoopRail owns first-chance recovery** (e.g. `retry_maker` replaces one maker).
   Engine health is the liveness backstop when rail does not fire
   ([IG-697](IG-697-engine-deadlock-recovery.md)).
5. **Wave “makers done”** requires makers **completed**, not merely
   terminal (failed/cancelled must not unlock integrate).

---

## Deliverables

- [x] RFC-204 / RFC-230 / LoopRail draft amendments (layering + exhaust rule)
- [x] `ContextEngine.send_back_goal`: rail-bound → `fail_goal` on exhaust
- [x] `AutopilotService`: emit `goal_failed` after rail exhaust; skip pytest
      hard-accept when `rail_id` set; consensus `suspend` on rail → fail+notify
- [x] Builtin `retry_maker` + catalog allowlist
- [x] `greenfield-system.yml`: `branch_is_stuck` → `retry_maker`
- [x] Structural `branch_is_stuck`; `wave_makers_done` / `needs_integrate`
      require all makers **completed**
- [x] Unit tests + `./scripts/verify_finally.sh`

---

## Control flow

```text
consensus send_back on rail subgoal
  → send_back_count += 1
  → if count >= max_send_backs:
       fail_goal(subgoal)
       notify_rail(goal_failed)
       greenfield: branch_is_stuck → retry_maker
         → replace maker only; rewire root depends_on
  → else: pending (retry worker)
```

---

## Out of scope

- ~~Auto-reset of send_back-exhausted goals in DAG health~~ — superseded by
  [IG-697](IG-697-engine-deadlock-recovery.md) (engine recovers **failed**
  rail workers that block pending dependents; still does not auto-reset
  **suspended** non-rail send-back exhaust)
- Git probes inside Autopilot consensus
- Changing StrangeLoop iteration budgets
- Reviving already-suspended goals without operator resume/cancel

---

## Acceptance

- [x] Rail maker exhaust → subgoal `failed`, rail fires `retry_maker`,
      siblings preserved
- [x] Non-rail exhaust → still `suspended` (operator resume)
- [x] Failed makers do not make `wave_makers_done` true
- [x] No pytest/git hard-accept for rail goals in AutopilotService
- [x] `./scripts/verify_finally.sh` green
- [x] No IG-/RFC- identifiers in user-facing runtime strings

---

## References

- Diagnosis: job `921c6d32` maker hang (2026-08-05)
- Follow-on: [IG-697](IG-697-engine-deadlock-recovery.md) engine deadlock recovery
- RFC-204 budget exhaustion amendment
- LoopRail §11 / §12 error handling
