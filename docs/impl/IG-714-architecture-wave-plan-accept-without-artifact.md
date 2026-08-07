# IG-714: Architecture accept without WavePlan (rail stall)

**Created**: 2026-08-07  
**Status**: Implemented (+ cleanse)  
**Superseded for persistence SoT**: [IG-720](IG-720-waveplan-ce-findings-no-file.md)
(CE findings + `rail_state` only; filesystem `wave-plan.json` removed).  
**Related**: [IG-704](IG-704-autopilot-wave-plan-host-ingest.md),
[IG-700](../archive/impl/IG-700-greenfield-fanout-closeout.md),
[IG-699](../archive/impl/IG-699-llm-determined-rail-fanout-width.md),
[RFC-232](../specs/RFC-232-waveplan-flat-semistructured-ingest.md)
(flat wire; nesting reject — follow-on),
RFC-630 (no keyword heuristics), RFC-222 (nano never sees GoalEngine)

---

## Goal

Close the production hole where a greenfield `architecture` / planner goal can
**complete** while `wave_plan_ready` stays false, so LoopRail never fires
`spawn_wave_makers` and the job root sits pending forever.

Ensure:

1. **Accept path** cannot mark architecture complete without host-applied
   WavePlan slices (from findings ingest into `RailJobState`).
2. **Filesystem plan files** (project tree or orphan job-dir JSON) remain
   **non-authoritative** and are never loaded as fan-out SoT.
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

> Persistence SoT updated by **IG-720**: apply WavePlan into `RailJobState`
> from CE findings; do **not** write or read `jobs/*/wave-plan.json`.

1. **Authoritative plan** = architecture goal findings → `record_wave_plan`
   apply into `rail_state.wave_slices` / `decompose_plan`.
2. **Host owns apply** — StrangeLoop / nano emit opaque findings; Autopilot
   parses structured WavePlan and calls `RailBuiltinExecutor.record_wave_plan`
   (IG-704). No Autopilot tools injected into CoreAgent.
3. **Deterministic architecture gate** when `require_plan` — on miss →
   `send_back` (or fail after budget); **never** fall through to free-form LLM
   consensus for architecture planner goals.
4. **No filesystem scrape** — project-tree or orphan job-dir JSON must not
   satisfy `wave_plan_ready` (RFC-630 / IG-720).
5. **Planner copy** — findings WavePlan JSON entry only; do not write fan-out
   policy into the project workspace.

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
- [x] On successful ingest, always update `rail_state.wave_slices` /
      `decompose_plan` before `complete_goal` (`record_wave_plan` apply path;
      IG-720 dropped the job-dir JSON file).
- [x] On `dag_idle` + `architecture_ready` with missing plan: rate-limited
      warning in `guards.py` (job id + WavePlan missing; no IG/RFC in string).
- [x] Review planner goal text: no callable `record_wave_plan`; findings-only
      WavePlan deliverable (no project-tree fan-out files).
- [x] Skill/wiki recovery points at CE findings / `rail_state.wave_slices`
      (IG-720); not filesystem `wave-plan.json`.

### C. Stuck-job recovery (ops + optional tooling)

For jobs already accepted without a plan (pattern: planner completed, zero
makers, rail_trace only `plan_milestones`):

1. Re-run architecture so findings include a **flat** WavePlan JSON object
   (`wave_slices` string list or flat `slices[]`; nested WAVE trees rejected),
   **or**
   set `wave_slices` on `rail_state.json`.
2. Wait for next `dag_idle` (or restart daemon) so `spawn_wave_makers` fires.
3. Or cancel / resubmit the job under a daemon that has the hard gate.

- [x] Document recovery in debug wiki / inspect-autopilot-job skill.
- [ ] Optional: admin/RPC or CLI helper to **record** a WavePlan for a job
      (deferred).
- [x] Job `4a0d82f2`: already recovered (auth/session slices).

### D. Tests

- [x] Architecture contribution with only workspace-style / prose findings →
      gate `send_back`; no `complete_goal`.
- [x] Valid WavePlan findings → `record_wave_plan` applies rail_state + accept
      (`test_architecture_gate_accepts_when_wave_plan_in_findings`).
- [x] Workspace / orphan job-dir plan files do not make `is_wave_plan_ready`
      true.
- [x] Fail-closed when rail interpreter is unset.
- [x] `./scripts/verify_finally.sh` green.

---

## Non-goals

- Scraping or promoting filesystem plan JSON to fan-out SoT.
- Keyword/regex judgment of planner prose for slice ids (RFC-630).
- Changing StrangeLoop Plan-Exec-Eval or injecting Autopilot tools into nano.
- Auto-reset of rail job roots by DAG health (separate from this IG).

---

## Acceptance

1. New greenfield architecture goals cannot complete without host-applied
   WavePlan when `require_plan` is true.
2. Presence of project-tree or orphan job-dir plan files alone never unblocks
   `spawn_wave_makers`.
3. Documented recovery via findings / `rail_state.wave_slices` (IG-720).
4. Verify green.

---

## References

- Host gate / ingest: `soothe.autopilot.service` —
  `_architecture_wave_plan_consensus_gate`, `_try_ingest_architecture_wave_plan`,
  `_ensure_rail_bound_for_job`
- Apply / ready: `soothe.autopilot.rail.builtins_exec` —
  `record_wave_plan`, `is_wave_plan_ready`, `_do_plan_milestones`
- Schema: `soothe.autopilot.rail.wave_plan` (IG-720: no file I/O helpers)
- Guard: `architecture_ready` + `wave_plan_ready` in
  `soothe.autopilot.rail.guards`
