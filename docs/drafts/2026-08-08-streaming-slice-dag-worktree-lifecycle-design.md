# Design Draft: Streaming Slice DAG + Host Worktree Lifecycle

**Status**: Formalized → [RFC-231 §9](../specs/RFC-231-looprail-rail-exec.md),
[RFC-232](../specs/RFC-232-waveplan-flat-semistructured-ingest.md) (slice
`depends_on` + catalog SoT). Implementation:
[IG-732](../impl/IG-732-streaming-slice-dag-worktree-lifecycle.md) (Draft).  
**Date**: 2026-08-08  
**Scope**: Remove wave/stage as an Autopilot **execution** boundary. Materialize
slice makers into the Context Engine DAG as dependencies become satisfied;
run them under pool concurrency in streaming parallel. Host-manage git
worktrees: merge each successful maker into a per-job integration branch,
refresh peer worktrees, resolve conflicts via focused goals, and land on
`main`/`master` only at job completion. Per-maker review/QA replace batch
wave integrate gates.  
**Related**: [RFC-231](../specs/RFC-231-looprail-rail-exec.md) (§9 streaming
slice catalog + host worktrees),
[RFC-232](../specs/RFC-232-waveplan-flat-semistructured-ingest.md) (flat
WavePlan + optional `depends_on`),
[RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md) (CE / engine),
[RFC-204](../specs/RFC-204-autopilot-mode.md),
historical [LoopRail design](2026-07-11-loop-rail-design.md).  
**Forensic trigger**: job `abe91be4` (greenfield-system) — three wave-1 makers
fan-out correctly, but six further WavePlan slices never entered the CE DAG
while pool slots sat idle; completed maker tips were not on `master`; host
`merge_branches` is unimplemented; batch integrate is an agent prompt deferred
until `wave_makers_done`.

---

## Problem

Today’s greenfield / migration rails treat **waves** as runtime stages:

1. Ingest a flat WavePlan, but only put the current `wave_slices` batch into
   `RailJobState` for spawn.
2. `spawn_wave_makers` creates makers for that batch only; later slices wait on
   `ready_for_next_wave` after integrate → commit → review → QA → feedback.
3. Maker briefs say “leave atomic commits for later integrate”; integrate is an
   **agent** goal, not a host merge. Catalog verb `merge_branches` returns
   skipped / not implemented.
4. Context Engine and the worker pool are already wave-agnostic (deps + capacity
   clamp). Artificial scarcity comes from the rail **not spawning** ready work.

Operators expect: a **DAG of goals** executed in streaming parallel under
concurrency limits; when one goal finishes, another pending goal acquires a
slot; worktree results sync into a shared base so peers stay coherent; the
**rail** is a cyclic workflow consumed only by Autopilot (not by CE), which
mutates the CE DAG to realize workflow logic.

---

## Goal

1. **Layering**: Rail YAML → Autopilot.service → CE goal mutations. CE never
   reads rails. CE execution = streaming / parallel under pool limits.
2. **No wave execution boundary**: Abolish `wave_index` gating,
   `ready_for_next_wave`, and batch `spawn_integrate` as the merge path.
3. **Slice catalog**: WavePlan becomes a flat slice catalog with optional
   per-slice `depends_on`. Autopilot spawns a maker when slice deps are
   satisfied (and the slice is not yet spawned).
4. **Host worktree lifecycle**: On maker success, host-merge into `job/<id>`;
   refresh/rebase remaining active worktrees; on conflict, spawn a resolve
   goal without pausing the whole job.
5. **Land on main late**: Shared base during the job is `job/<id>`; merge to
   `main`/`master` only at the job completion gate.
6. **Quality without batch stages**: Drop batch integrate; after a successful
   host land on `job/<id>`, rail spawns **per-maker** review → QA. Feedback
   attaches to that lineage when QA/acceptance fails.

---

## Non-Goals

- Teaching CE or the worker pool about waves, slices, or rails.
- Nested WavePlan trees (still forbidden — RFC-232).
- Keyword/regex content judgment for independence (RFC-630); independence and
  deps come from structured WavePlan fields or planner structured output.
- Multi-job worktree GC as a hard requirement for MVP (optional follow-up).
- Changing StrangeLoop / CoreAgent internals; only Autopilot rail builtins,
  rail YAML, WavePlan schema, and host git helpers.
- Making review/QA block unrelated ready makers (they must not).

---

## Decisions

| Topic | Decision |
|-------|----------|
| Spawn policy | Grow CE DAG as slice deps become satisfied (option B) |
| Merge timing | Host auto-merge on maker success + refresh peer WTs (option A) |
| Shared base | Per-job branch `job/<job_id>` (option B); land on main at job complete |
| Merge conflict | Spawn focused resolve goal; rest of DAG keeps running (option A) |
| Slice deps | Optional `depends_on` on flat slice entries; omitted ⇒ ready after architecture (option C) |
| Integrate / review / QA | No batch integrate; per-maker review→QA after successful host merge (option A) |
| Wave counters | Demote: no runtime gate; optional expansion budget (`max_slices`) replaces `max_waves` if a cap is needed |
| `merge_branches` | Implement as host primitive used by merge-on-success and final land |
| Engine / CE | Remain wave-agnostic; only Autopilot + rail state change |

---

## Architecture

```text
WavePlan (flat slices ± depends_on)
        │ ingest once (architecture done / dump reuse)
        ▼
RailJobState.slice_catalog     ← planning SoT (not wave rounds)
        │
        ▼
Autopilot + LoopRail (event-driven)
  events: job_start | goal_completed | goal_failed | dag_idle
    • spawn makers for newly ready unspawned slices
    • on maker success: host merge → job/<id>, refresh WTs
    • on merge conflict: spawn resolve goal (lineage only)
    • on successful land: spawn per-maker review → QA
    • on job acceptance: host land job/<id> → main, complete_job
        │
        ▼
Context Engine DAG (no wave/stage concept)
  ready = depends_on terminal
        │
        ▼
Worker pool (max_parallel / engine clamp) — streaming fill
```

### Layer responsibilities

| Layer | Owns | Must not own |
|-------|------|----------------|
| CE | Goal graph, status, `depends_on`, workspace paths | Rail YAML, wave index, slice catalog |
| Autopilot engine | Pool, dispatch, capacity clamp, report-commit | Slice ids as engine API |
| LoopRail / Autopilot service | Rail flow, catalog verbs, spawn/merge/land, annotations | Direct CE “wave” fields |
| Host git helper | Worktree add/remove, merge, rebase/refresh, land | LLM content judgment |

---

## Components

### 1. Slice catalog (`RailJobState`)

Replace runtime batch fields used as spawn gates:

| Field | Role |
|-------|------|
| `slices[]` | `{slice, description?, tags?, depends_on?: [slice_id…], priority?}` |
| `spawned_slices` | map `slice_id → goal_id` (idempotent spawn) |
| `job_branch` | e.g. `job/<full_or_short_id>` — integration tip |
| `base_branch` | usually `main` or `master` (detected once) |
| `max_slices` | optional expansion budget (successor to `max_waves`) |

**Migration**: Accept today’s `wave_slices` + rich `slices[]` on ingest; flatten
into the catalog. Ignore nested wave trees (unchanged). Stop advancing
`wave_index` as a spawn gate; may keep the field temporarily for trace
compat then remove in a cleanse pass.

### 2. Spawn controller

Builtin (rename conceptually from `spawn_wave_makers` → `spawn_ready_makers`
or keep the verb name with new semantics):

**Ready rule**: slice S is ready iff every name in `S.depends_on` is either
absent (treat as none) or maps via `spawned_slices` to a goal in a **terminal
success** state (completed), and S is not already in `spawned_slices`.

**Trigger**: `architecture_ready` (catalog non-empty, architecture terminal),
and thereafter `goal_completed` / `dag_idle` when new slices may have unblocked.

**Wiring**:

- Maker `depends_on` in CE: architecture goal + CE goals for slice deps (not
  the job root — children must never depend on an active root).
- Root `depends_on`: union of spawned makers (and later land gate), coordinator
  pattern unchanged.
- Workspace: `.soothe/worktrees/<slug>` when worktrees enabled; branch
  `job/<id>/<slug>` (drop mandatory `wN` segment; optional tag still allowed).

### 3. Worktree manager (host)

| Operation | Behavior |
|-----------|----------|
| Ensure job branch | Create `job/<id>` from `base_branch` if missing |
| Ensure maker WT | `git worktree add` on maker branch from current `job/<id>` tip |
| Merge on success | Merge maker branch into `job/<id>` in the primary repo (or a dedicated merge WT) |
| Refresh peers | For each other active maker WT: rebase or reset-merge onto new `job/<id>` tip (prefer rebase of maker branch; document dirty-tree policy: stash fail → annotate + resolve) |
| Conflict | Abort merge; spawn resolve goal (see below); do not suspend job |
| Prune | On maker terminal + merged (or abandoned): remove WT; keep branch until land or GC policy |
| Final land | Fast-forward or merge `job/<id>` into `base_branch`; fail → resolve/land goal |

Maker goal briefs change from “leave commits for later integrate” to “commit on
this branch; host will merge into the job branch when you complete.”

### 4. Merge / resolve

- Happy path: host merge, annotate maker `branch_status=merged`, record tip SHA
  on rail annotations.
- Conflict: annotate `branch_status=conflict`; create resolve goal in the
  conflicting worktree (or primary) depending on the conflicted maker + job
  branch; on resolve success, retry host merge once; on repeated failure,
  `retry_maker` / feedback lineage — still non-global.
- `merge_branches` catalog verb: implement as the host primitive (or thin
  wrapper) so custom rails can call it; greenfield uses it implicitly on
  maker success and on final land.

### 5. Per-maker quality chain

After **successful** host merge of maker M:

1. Spawn `review` goal (diff-scoped to M’s merge range on `job/<id>`).
2. On review pass/skip policy → spawn `qa_verify` for that range / slice tags.
3. On QA fail → existing feedback macros (`spawn_feedback_cycle`) **scoped to
   that slice / lineage**, not “wave complete.”
4. These goals must **not** appear in `depends_on` of unrelated ready makers.

Batch `spawn_integrate` and `needs_commit` as wave barriers are removed from
greenfield. Optional atomic commit hygiene can remain inside the maker loop or
as a light host `git status` check before merge (no separate milestone stage
required for MVP).

### 6. Job completion land gate

When rail condition `job_complete` (acceptance + idle / no pending children):

1. Host land `job/<id>` → `base_branch`.
2. On success → `complete_job`.
3. On conflict → land-resolve goal; do not mark job complete.

---

## Rail flow sketch (greenfield-system)

Conceptual event graph (cyclic, Autopilot-consumed only):

```text
job_start → plan_milestones
goal_completed/dag_idle + architecture_ready → spawn_ready_makers
goal_completed + maker_success → host_merge_and_refresh
                              → spawn_review (per maker)
                              → spawn_ready_makers  (unblocked slices)
goal_completed + review_ok → qa_verify (per maker)
goal_failed/completed + needs_feedback → spawn_feedback_cycle (lineage)
goal_failed + maker_stuck → retry_maker
dag_idle + job_complete → land_on_base → complete_job
```

Conditions are rephrased away from `wave_makers_done` / `ready_for_next_wave`
toward catalog emptiness, lineage status, and acceptance.

Migration rail may keep an explicit **cutover pause** (`needs_human`) without
reintroducing wave spawn gates; fan-out uses the same slice catalog.

---

## Data flow (happy path)

1. Submit job with `--rail greenfield-system` (or bound rail).
2. Planner (or dump short-circuit) produces flat WavePlan → catalog ingest.
3. Ensure `job/<id>` from main/master.
4. Spawn all ready makers (no deps or deps already done); pool runs ≤ N.
5. Maker A completes → merge to `job/<id>` → refresh B’s WT → spawn A’s
   review→QA; if C depended on A, spawn C.
6. Pool immediately claims C when a slot frees (streaming).
7. Acceptance + idle → land `job/<id>` on main → complete.

---

## Error handling

| Case | Behavior |
|------|----------|
| Merge conflict | Resolve goal on lineage; siblings continue |
| Dirty peer WT on refresh | Fail refresh for that WT; annotate; optional resolve; do not kill other makers |
| Review/QA fail | Feedback/retry on lineage only |
| Architecture fail | `retry_architecture` (unchanged idea) |
| Land conflict at end | Land-resolve; job stays open |
| Stale WTs from other jobs | Out of merge scope; optional GC follow-up |
| Cross-job root deps | Treat as bug/noise; root should wait only on own catalog + land |

---

## Testing

| Case | Expect |
|------|--------|
| Independent A∥B, cap=2 | Both active; neither waits on a wave barrier |
| C depends on A | C absent until A merged; then spawned and eligible |
| Cap=1, three independent | Sequential slot fill as each completes |
| Merge success | `job/<id>` contains A’s tip; B’s WT sees files after refresh |
| Forced conflict | Resolve goal created; third independent slice still dispatches |
| Per-maker QA fail | Feedback on that slice; other makers unaffected |
| Job complete | `base_branch` advances; mid-job `base_branch` unchanged |
| CE/engine | No new wave APIs; snapshot has no wave fields on goals |

---

## Migration / compatibility

1. **Ingest**: Continue accepting `wave_slices` string lists and rich `slices[]`;
   map into catalog. Document optional `depends_on` on slice objects (RFC-232
   amendment or successor section).
2. **Rails**: Update `greenfield-system.yml` and `migration.yml` flow/conditions;
   demote fanout `max_waves` → `max_slices` (or keep key as alias).
3. **State**: Read old `rail_state.json` with `wave_index` / `wave_slices`;
   upgrade on load to catalog; traces may still log legacy names briefly.
4. **Verb names**: Prefer keeping catalog verb ids stable where possible
   (`spawn_wave_makers` implements ready-spawn) to avoid breaking custom rails;
   document semantic change. Add/implement `merge_branches` / `land_job_branch`.
5. **Cleanse**: After impl, remove dead wave-gate conditions, batch integrate
   spawn path, and “later integrate” maker copy (per Critical Rule 6, with
   user approval).

---

## Rollout

1. Host git helper + `merge_branches` + merge-on-success + refresh (feature
   flagged if needed).
2. Slice catalog ingest + `spawn_ready_makers` semantics.
3. Greenfield YAML condition rewrite + per-maker review/QA spawn.
4. Final land gate on `job_complete`.
5. Migration rail parity; docs / debug wiki; forensic skill notes (wave stall
   → catalog stall).

---

## Open questions (non-blocking)

1. Refresh strategy default: rebase vs merge-from-job-branch onto maker branch.
2. Whether commit milestone evidence for review is `git log job/<id>` range
   only, or attach maker branch SHAs in annotations.
3. Short vs full job id in branch names (`job/abe91be4` vs full uuid) — match
   existing `job/{job_id[:8]}/…` convention unless we standardize on full id.
4. Optional opportunistic GC of worktrees whose job root is cancelled/completed.

---

## Self-review checklist

- [x] No TBD placeholders in normative decisions  
- [x] Layering consistent: rail → Autopilot → CE; CE wave-free  
- [x] Spawn, merge, conflict, quality, land covered  
- [x] Scope bounded to Autopilot/rail/host git + WavePlan schema  
- [x] Ambiguity on refresh/rebase called out under open questions, not as
      silent assumptions in the happy path  
