# IG-714: Architecture accept without job-scoped WavePlan (rail stall)

**Created**: 2026-08-07  
**Status**: Implemented (+ cleanse)  
**Related**: [IG-704](IG-704-autopilot-wave-plan-host-ingest.md),
[IG-700](../archive/impl/IG-700-greenfield-fanout-closeout.md),
[IG-699](../archive/impl/IG-699-llm-determined-rail-fanout-width.md),
RFC-630 (no keyword heuristics), RFC-222 (nano never sees GoalEngine)

---

## Goal

Close the production hole where a greenfield `architecture` / planner goal can
**complete** while `wave_plan_ready` stays false, so LoopRail never fires
`spawn_wave_makers` and the job root sits pending forever.

Ensure:

1. **Accept path** cannot mark architecture complete without a host-persisted
   job-scoped WavePlan (or equivalent findings ingest).
2. **Workspace files** (`docs/wave-plan.json`, `.soothe/wave-plan.json`, bare
   `wave-plan.json` under the project tree) remain **non-authoritative** and are
   never loaded as fan-out SoT.
3. **Operators** have a clear recovery path when a job is already stuck.
4. **Agents** are not steered toward writing fan-out policy into the repo.

---

## Incident (job `4a0d82f2`)

| Fact | Detail |
|------|--------|
| Rail | `greenfield-system` (`require_plan: true`) |
| Planner | `c857b2ec` completed 2026-08-06 ~18:28 |
| Agent behavior | Wrote `docs/wave-plan.json` (+ guides) under the **project workspace** |
| Host ingest | Never ran successfully — findings were step prose, not WavePlan JSON |
| Consensus | Soft LLM `evaluate_goal_completion` → **accept** (`Consensus decided accept`) |
| Hard gate | `_architecture_wave_plan_consensus_gate` (IG-704) landed in tree **~4h later** (`69ccdbd18`); **not** in the running daemon at accept time |
| Rail after accept | `architecture_done=True`, `wave_plan_ready=False` → `spawn_wave_makers` short-circuits on every `dag_idle` |
| Root | Skipped for schedule (rail job root); job appears “stuck pending” |

Workspace multi-wave product docs do **not** validate as host `WavePlan`
(`wave_slices` / `slices` schema; pre-Slice `wave_modules` / `modules` keys
are rejected). Copying them into
`$SOOTHE_DATA_DIR/jobs/{job_id}/wave-plan.json` without conversion fails closed.

---

## Design rules (MUST)

1. **Authoritative artifact only** under
   `$SOOTHE_DATA_DIR/jobs/{job_id}/wave-plan.json` (template
   `{job_id}/wave-plan.json` via `jobs_root`). Legacy workspace artifact
   templates (`.soothe/wave-plan.json`, `wave-plan.json`) are rewritten to the
   job-scoped default and **never loaded** from the project tree
   (`wave_plan.py`).
2. **Host owns persist** — StrangeLoop / nano emit opaque findings; Autopilot
   parses structured WavePlan and calls `RailBuiltinExecutor.record_wave_plan`
   (IG-704). No Autopilot tools injected into CoreAgent.
3. **Deterministic architecture gate** when `require_plan` — on miss →
   `send_back` (or fail after budget); **never** fall through to free-form LLM
   consensus for architecture planner goals.
4. **No workspace scrape** — do not read `docs/wave-plan.json` (or any project
   path) to satisfy `wave_plan_ready` (RFC-630 / IG-700).
5. **Planner copy** — continue to forbid writing fan-out policy into the
   project workspace tree; required deliverable is a findings WavePlan JSON
   entry only (`_do_plan_milestones`).

---

## Work items

### A. Verify gate is live (deploy / runtime)

- [x] Confirm running daemon includes IG-704 gate (`Architecture wave-plan gate`
      log line on architecture finalize).
- [x] Document: after upgrading soothe packages, operators must
      `soothed restart` before new greenfield jobs (stale process = soft
      consensus hole) — `docs/wiki/howto_debug.md`, inspect-autopilot-job skill.
- [x] Add a unit/integration assertion that architecture finalize **never**
      calls `evaluate_goal_completion` when `require_plan` and goal is planner
      (`test_architecture_gate_never_calls_llm_consensus`).

### B. Harden accept / ingest (product)

- [x] Audit `_apply_consensus_and_finalize`: architecture + `require_plan` →
      gate always returns accept/send_back; no silent `None` fall-through when
      rail interpreter / job state is temporarily unbound (rebind or fail closed)
      — `_ensure_rail_bound_for_job` + fail-closed send_back.
- [x] On successful ingest, always persist job-scoped file + update
      `rail_state.wave_slices` / `decompose_plan` before `complete_goal`
      (existing `record_wave_plan` path; covered by gate accept test).
- [x] On `dag_idle` + `architecture_ready` with missing plan: rate-limited
      warning in `guards.py` (job id + WavePlan missing; no IG/RFC in string).
- [x] Review planner goal text: no callable `record_wave_plan`; explicit
      forbid `docs/wave-plan.json` / `.soothe/wave-plan.json`.
- [x] Skill/wiki point at `jobs/{id}/wave-plan.json` only; no product writers
      for workspace wave-plan files.

### C. Stuck-job recovery (ops + optional tooling)

For jobs already accepted without artifact (pattern: planner completed, zero
makers, rail_trace only `plan_milestones`):

1. Seed a **valid** host WavePlan at
   `$SOOTHE_DATA_DIR/jobs/{job_id}/wave-plan.json`.
2. Wait for next `dag_idle` (or restart daemon) so `spawn_wave_makers` fires.
3. Or cancel / resubmit the job under a daemon that has the hard gate.

- [x] Document recovery in debug wiki / inspect-autopilot-job skill.
- [ ] Optional: admin/RPC or CLI helper to **record** a WavePlan for a job
      (deferred — seed file is sufficient).
- [x] Job `4a0d82f2`: already recovered via manual seed (auth/session slices).

### D. Tests

- [x] Architecture contribution with only workspace-style / prose findings →
      gate `send_back`; no `complete_goal`.
- [x] Valid WavePlan findings → `record_wave_plan` writes under `jobs_root`,
      accept (`test_architecture_gate_accepts_when_wave_plan_in_findings`).
- [x] Workspace `docs/wave-plan.json` does not make `is_wave_plan_ready` true.
- [x] Fail-closed when rail interpreter is unset.
- [x] `./scripts/verify_finally.sh` green.

---

## Non-goals

- Scraping or promoting `docs/wave-plan.json` (or any project tree path) to
  fan-out SoT.
- Keyword/regex judgment of planner prose for slice ids (RFC-630).
- Changing StrangeLoop Plan-Exec-Eval or injecting Autopilot tools into nano.
- Auto-reset of rail job roots by DAG health (separate from this IG).

---

## Acceptance

1. New greenfield architecture goals cannot complete without a host-persisted
   WavePlan when `require_plan` is true.
2. Presence of project-tree `**/wave-plan.json` alone never unblocks
   `spawn_wave_makers`.
3. Documented recovery for pre-gate stuck jobs; skill/wiki point at
   `jobs/{id}/wave-plan.json` only.
4. Verify green.

---

## References

- Host gate / ingest: `soothe.autopilot.service` —
  `_architecture_wave_plan_consensus_gate`, `_try_ingest_architecture_wave_plan`,
  `_ensure_rail_bound_for_job`
- Persist / ready: `soothe.autopilot.rail.builtins_exec` —
  `record_wave_plan`, `is_wave_plan_ready`, `_do_plan_milestones`
- Schema / legacy rewrite: `soothe.autopilot.rail.wave_plan`
- Guard: `architecture_ready` + `wave_plan_ready` in
  `soothe.autopilot.rail.guards`
