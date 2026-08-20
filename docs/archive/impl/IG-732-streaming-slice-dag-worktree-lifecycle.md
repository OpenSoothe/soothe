# IG-732: Streaming slice DAG + host worktree lifecycle

**Created**: 2026-08-08  
**Status**: In progress (P0–P3 landed; verify_finally pending)  
**Package**: `soothe`  
**Related**: [RFC-231 §8–§9](../specs/RFC-231-looprail-rail-exec.md),
[RFC-232](../specs/RFC-232-waveplan-flat-semistructured-ingest.md),
[RFC-230 §8](../specs/RFC-230-job-maturity-assessment.md),
design draft
[2026-08-08-streaming-slice-dag-worktree-lifecycle-design.md](../drafts/2026-08-08-streaming-slice-dag-worktree-lifecycle-design.md),
[IG-722](IG-722-waveplan-multiform-transfer.md),
[IG-721](IG-721-waveplan-flat-semistructured-ingest.md),
[IG-715](IG-715-migration-wave-fanout.md),
[IG-730](IG-730-waveplan-continue-short-circuit.md)

---

## Goal

Remove **wave/stage as an Autopilot execution boundary**. After WavePlan
ingest, Autopilot **stream-spawns** maker goals into the Context Engine DAG as
slice deps become satisfied; the worker pool fills under concurrency. Host
**merges** each successful maker into `job/<id>`, refreshes peer worktrees,
spawns conflict resolve / per-maker review→QA without freezing unrelated
makers, and **lands** `job/<id>` on `main`/`master` only at job complete.

CE and the engine remain wave-agnostic (deps + capacity only). LoopRail is
consumed only by AutopilotService.

Forensic trigger: job `abe91be4` — three wave-1 makers ran; six further
catalog slices never entered the CE DAG while pool slots sat idle; completed
tips were not on `master`; `merge_branches` was unimplemented.

---

## Design rules (MUST)

1. **Layering** — Rail YAML → Autopilot → CE mutations. CE MUST NOT read rails
   or grow wave fields on goals.
2. **No wave spawn gate** — `wave_index` / `wave_makers_done` /
   `ready_for_next_wave` MUST NOT withhold ready catalog slices from the DAG
   (RFC-231 §8–§9). Optional `max_slices` (alias `max_waves`) is an expansion
   budget only (`below_slice_budget` structural flag; not a `job_complete`
   veto once `acceptance_met` is latched).
3. **Spawn-ready** — `spawn_wave_makers` creates makers only for **unspawned**
   slices whose `depends_on` peer slices map to **completed** makers (or have
   no deps). Re-fire on `goal_completed` / `dag_idle` when
   `slices_ready_to_spawn`.
4. **Slice deps** — optional on rich WavePlan `slices[]` (RFC-232); omitted ⇒
   ready after architecture. Validate unknown / self / cycle → reject /
   send_back at ingest.
5. **Child→root ban** — makers MUST NOT `depends_on` the active job root.
6. **Host merge on success** — on maker terminal success, host-merge maker
   branch into `job_branch`; refresh other active maker WTs; annotate
   `branch_status=merged`. No agent batch integrate as the merge path.
7. **Conflict isolation** — merge conflict → resolve goal on that lineage;
   do **not** suspend the whole job; siblings keep running.
8. **Per-maker quality** — after successful merge, spawn review → QA for that
   land range; MUST NOT add those goals as deps of unrelated ready makers.
9. **Late land** — `land_job_branch` on `job_complete` only; then
   `complete_job`.
10. **Briefs** — maker copy MUST NOT say “leave commits for later integrate”;
    MUST state host merges into the job branch on completion. No IG-/RFC- ids
    in user-visible strings.
11. **Config / templates** — if any new autopilot knobs are added, sync
    `config/*.template.yml`, develop copy, and daemon setup templates
    (AGENTS.md Critical Rule 2).
12. **Tests first for behavior** — fix implementation, not expectations
    (Critical Rule 8).

---

## Deliverables

### P0 — WavePlan + RailJobState catalog

- [x] `WavePlanSlice.depends_on: list[str]` (+ cycle/unknown/self validation)
- [x] `WavePlan.max_slices` (prefer); keep `max_waves` as alias into budget
- [x] `as_decompose_plan()` persists `depends_on`
- [x] `RailJobState`: `spawned_slices`, `job_branch`, `base_branch`,
      `max_slices`; `wave_index` not a spawn gate
- [x] Persist/load new fields in `rail_state.json`
- [x] Upgrade path: rebuild `spawned_slices` from annotations when empty

### P1 — Host git / worktree manager

- [x] `soothe/autopilot/rails/worktree_ops.py`
- [x] Ensure `job/<id>/_base` from detected `base_branch` (`main`/`master`)
- [x] Maker WT from job-branch tip; `job/<id>/<slug>` (no nested ref clash)
- [x] merge / refresh / land helpers
- [x] `_do_merge_branches` implemented (not skipped)
- [x] `_do_land_job_branch` + land before `complete_job`

### P2 — Streaming spawn + rail YAML

- [x] `_do_spawn_wave_makers` → spawn-ready; CE deps from slice deps
- [x] Flow: `maker_needs_merge` → merge; `slices_ready_to_spawn` → spawn
- [x] `greenfield-system.yml` + `migration.yml` streaming rewrite
- [x] Guards: `slices_ready_to_spawn`, `maker_needs_merge`;
      `ready_for_next_wave` aliases to slices-ready
- [x] Maker briefs: host-merge wording
- [ ] Builtin README + debug wiki + inspect skill notes (docs polish)

### P3 — Merge / quality / conflict reactions

- [x] Maker success → host merge + peer refresh; conflict → resolve goal
- [x] After merge → per-maker review + spawn-ready
- [x] Greenfield no longer uses batch `spawn_integrate` in flow
- [x] `branch_status` includes `merged` / `conflict` on rail annotations

### P4 — Merge resilience (happy-path host + agent resolve)

Forensic follow-up: job `abe91be4` — dirty primary blocked `checkout`
of `job/<id>/_base`; late-slice `merge_branches` returned bare `error`
with no retry; unborn maker worktrees never got tips.

- [x] Host merge only in isolated `.soothe/merge/_host` worktree (never
      checkout job branch in dirty primary)
- [x] Thin materialize tip (one best-effort commit); else `needs_agent`
- [x] Conflict **or** any complex failure → spawn/reuse resolve StrangeLoop
      goal (tool-oriented brief); do not wedge rail with bare `error`
- [x] `dag_idle` + `maker_needs_merge` → `merge_branches` (greenfield +
      migration); resolve completion re-enters merge
- [x] Unit: dirty primary merge; conflict flag; unborn WT materialize;
      resolve spawn; idle/resolve guards
- [ ] `./scripts/verify_finally.sh` green before commit

### Continue stuck job (operator runbook)

After upgrading the daemon and `soothed restart`:

1. Leave `.soothe/worktrees/*` in place; optionally stash/commit dirty
   primary files.
2. Idle fires `merge_branches` for makers still `branch_status=active|conflict`.
3. Host merges happy-path **or** spawns resolve goals; workers fix git;
   host retries until annotations show `merged`.
4. Confirm unity: `git ls-tree -r job/<id>/_base` contains late slices.
5. Integration ≠ acceptance — job may still need maturity / feedback
   budget / operator stop separately (`acceptance_met`).

### P5 — Tests (earlier)

- [x] Unit: WavePlan `depends_on` accept / unknown / cycle reject
- [x] Unit: spawn-ready A∥B; C→A waits
- [x] Unit: merge without git annotates + spawns review / ready slices
- [x] Rails suite updated (140 unit/rails tests green)
- [ ] Pool cap=1 sequential fill (scheduler integration — optional follow-on)
- [ ] Merge conflict + land conflict git integration tests (optional)

---

## Out of scope

- CE / StrangeLoop API changes for waves
- Nested WavePlan support
- Multi-job opportunistic worktree GC (optional follow-on)
- Keyword independence heuristics (RFC-630)
- Full Rail Exec M4 intent expand
- Changing report-commit judge ownership (RFC-204)

---

## Suggested module layout

```text
packages/soothe/src/soothe/autopilot/rails/
  wave_plan.py           # + depends_on, max_slices, validation
  builtins_exec.py       # RailJobState fields; spawn-ready; merge/land hooks
  worktree_ops.py        # NEW: ensure job branch, merge, refresh, land
  guards.py / predicates # slices_ready_to_spawn, maker_merged, …
packages/soothe/src/soothe/autopilot/rails/builtin_rails/
  greenfield-system.yml
  migration.yml
  README.md
packages/soothe/tests/unit/autopilot/rail/
  test_streaming_spawn.py
  test_worktree_ops.py
  test_wave_plan_depends_on.py
```

---

## Algorithms (normative sketches)

### Spawn-ready

```text
catalog = state.decompose_plan or synthetic from wave_slices
for slice S in catalog:
  if S.id in state.spawned_slices: continue
  if any(dep not in spawned or goal(dep).status != completed
         for dep in S.depends_on): continue
  create maker goal; annotate; spawned_slices[S.id] = goal_id
  wire CE depends_on = [architecture?, *dep_goal_ids]
root.depends_on ∪= new maker ids
```

### Merge-on-success

```text
on maker goal completed (role=maker, branch set)
  or dag_idle with unmerged makers
  or resolve goal completed:
  ensure job_branch; optional one-shot materialize source tip
  result = merge in .soothe/merge/_host (not primary checkout)
  if conflict or needs_agent:
    annotate conflict; spawn/reuse resolve StrangeLoop; return success
  annotate merged; refresh_peer_worktrees()
  spawn review(M) → (on ok) qa_verify(M)
  invoke spawn_wave_makers (ready set may have grown)
```

---

## Verification

| Case | Expect |
|------|--------|
| Independent A∥B | Both CE goals exist; pool may run both under cap |
| C depends_on A | C absent until A completed + merged map updated |
| Cap=1, 3 independent | Slot refilled after each completion |
| Merge | `job/<id>` contains maker tip; peers refreshed |
| Conflict | Resolve goal; other slices still dispatch |
| Job complete | `base_branch` advances; mid-job base unchanged |
| CE snapshot | No wave fields on goals |

Manual: re-run a greenfield continue job with a 9-slice WavePlan and
`engine_max_parallel_goals=2` — observe streaming fill and job-branch merges
without waiting for a batch integrate.

---

## Cleanse (after impl — approved 2026-08-09)

- [x] Greenfield/migration: no batch `spawn_integrate` / `wave_makers_done` flow
- [x] Maker / retry briefs: host-merge wording (no “later integrate”)
- [x] `_do_spawn_integrate` / `_do_commit_milestone`: custom-rail only; no wave tags
- [x] Duplicate `ready_for_next_wave` migration flow entries removed
- [x] Debug wiki + inspect-autopilot-job skill: streaming spawn / merge notes
- [x] `job_maturity` RailSignal includes `slices_ready_to_spawn`
- Kept: `wave_makers_done` / `ready_for_next_wave` guards as legacy aliases;
  `spawn_integrate` catalog verb for custom rails; `wave_index` for trace

## Cleanse (P4 merge resilience — approved 2026-08-09)

- [x] Remove thin `_ensure_worktree` wrapper (call `worktree_ops.ensure_worktree`)
- [x] Drop duplicate `ensure_job_branch` before `merge_branch_into`
- [x] Drop redundant post-materialize tip check; simplify failure → resolve gate
- [x] Simplify resolve-inflight skip (completed resolve is not inflight)
- [x] Drop `_branch_tip_exists` wrapper (use `_ref_exists`)
- Kept: custom-rail `spawn_integrate` / `commit_milestone` + legacy guards
- [x] `./scripts/verify_finally.sh` after cleanse

---

## Implementation notes

- Prefer extending existing `_ensure_worktree` rather than a second git stack.
- Reuse `subprocess` git patterns already in `builtins_exec.py`; keep ops
  synchronous-safe behind `asyncio.to_thread` if they block.
- Verb name `spawn_wave_makers` stays for catalog compatibility; semantics =
  spawn-ready (RFC-231).
- No feature-flag dual-path — hard cut with rail_state upgrade fields
  (`spawned_slices`, `job_branch`, `base_branch`).

---

## Exit criteria

- [x] RFC-231 §9 / RFC-232 `depends_on` behaviors covered by unit tests
- [x] Greenfield + migration YAML match streaming flow
- [x] `merge_branches` / land no longer stubbed
- [x] `./scripts/verify_finally.sh` green (Tencent default mirror + lock URL
      rewrite to PyPI; `requires-python` capped `<3.14` so CI `uv sync --frozen`
      no longer dies on the win32/3.14 soothe-nano split)
- [x] Design draft + RFCs point at this IG as implementing
