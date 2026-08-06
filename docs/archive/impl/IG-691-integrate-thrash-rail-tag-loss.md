# IG-691: Integrate Consensus Thrash + Rail Tag Loss After Restart

**Created**: 2026-08-05  
**Status**: Implemented  
**Related**: [IG-678](IG-678-autopilot-ce-rails-production-readiness.md) (RL-4 / P2-2),
[IG-687](IG-687-greenfield-system-rail.md),
[IG-690](IG-690-consensus-pass-full-evidence.md),
[RFC-204](../specs/RFC-204-autopilot-mode.md),
[RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md)

---

## Incident

Job `20999e64` (`greenfield-system`, workspace `ccc-scaffold`) appeared hung
for ~40+ minutes after Wave 1 makers completed.

| Phase | Symptom |
|-------|---------|
| A | Integrate goal `ffe74f6d` thrashing: consensus `send_back` → budget
     exhaust → `suspend` → DAG health `reset_goals` → redispatch |
| B | After consensus finally `accept`, root stayed `pending`: scheduler
     skips rail job roots; rail did not spawn `commit_milestone` because
     `trigger_tags=[]` after daemon restart |

---

## Root causes

1. **Health vs consensus**: `apply_health_report` reactivated any suspended
   goal; `reactivate_goal` also cleared `send_back_count`, undoing budget.
2. **Ephemeral rail tags**: `tags_by_goal` read only in-memory
   `RailJobState`; restart emptied annotations even when CE
   `GoalNode.rail_tags` still held `integrate`.

---

## Fix (shipped)

### P0-1 — CE tag fallback + hydrate on bind

- `tags_by_goal` unions in-memory annotations with descendant
  `GoalNode.rail_tags`.
- `bind_job` hydrates annotations from CE before use.

### P0-2 — Persist `rail_state.json`

- Under `data/jobs/{job_id}/rail_state.json` (same jobs root as rail trace).
- Load/merge on `bind_job`; write on annotate / wave / feedback / complete.
- `LoopRailInterpreter(..., jobs_root=)` wired from AutopilotService.

### P0-3 — Health skip consensus-exhausted suspends

- `apply_health_report`: skip `suggest_reset` when
  `status==suspended` and `send_back_count >= max_send_backs`.
- DAG health prompt documents the same constraint.
- Operator `soothe autopilot resume` still reactivates (resets budget by
  design).

### Out of this IG (still optional)

- P1 structural git probe / send_back checklist for integrate.
- Automatic re-fire of `goal_completed` for already-stuck roots after upgrade.
- Job maturity latch / production `dag_idle` / verifier rail exclusivity
  (→ [IG-692](IG-692-job-maturity-assessment.md) / [RFC-230](../specs/RFC-230-job-maturity-assessment.md)).

---

## Acceptance

- [x] Empty `_jobs` + CE `rail_tags=["integrate"]` → `needs_commit` matches
- [x] `rail_state.json` restores annotations / `wave_index` on new executor
- [x] Health reset skipped for send_back-exhausted suspends; ordinary
      suspend still reactivates
- [x] Unit tests in `test_greenfield_system_rail.py` +
      `test_ig680_health_evidence_deps.py`
- [x] `./scripts/verify_finally.sh` green

---

## Files

| Path | Change |
|------|--------|
| `autopilot/rail/builtins_exec.py` | CE fallback, hydrate, persist |
| `autopilot/rail/interpreter.py` | `jobs_root` → executor |
| `autopilot/service.py` | Pass `jobs_root=trace_root` |
| `autopilot/goal_dag_verifier.py` | Health reset filter |
| `autopilot/verifier_prompts.py` | Reset guidance |
| `tests/unit/rails/test_greenfield_system_rail.py` | Tag / persist tests |
| `tests/unit/core/autopilot/test_ig680_health_evidence_deps.py` | Health filter tests |

---

## Notes

- User-facing logs/CLI must not mention this IG id.
- Stuck jobs that already lost tags and finished integrate may need a one-shot
  rail rebind + event after upgrade, or operator resume of a commit goal.
