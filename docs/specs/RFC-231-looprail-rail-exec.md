# RFC-231: LoopRail and Rail Exec (Composable Verb Bodies)

**RFC**: 231  
**Title**: LoopRail and Rail Exec (Composable Verb Bodies)  
**Status**: Draft  
**Kind**: Architecture Design  
**Created**: 2026-08-07  
**Updated**: 2026-08-08  
**Authors**: Soothe Team  
**Depends on**: RFC-204, RFC-222, RFC-228, RFC-230, RFC-625, RFC-626, RFC-630  
**Related**: RFC-232 (flat WavePlan wire ingest), LoopRail design draft
(`docs/drafts/2026-07-11-loop-rail-design.md`),
design draft `docs/drafts/2026-08-08-llm-rail-auto-pick-design.md` (§10 selection),
design draft `docs/drafts/2026-08-08-streaming-slice-dag-worktree-lifecycle-design.md`
(§9 streaming slice DAG + host worktrees),
design draft `docs/archive/drafts/2026-08-08-autopilot-report-commit-judgment-design.md`,
IG-678, IG-687, IG-691, IG-692, IG-693, IG-700, IG-704, IG-714, IG-715, IG-720,
IG-728 (LLM rail auto-pick)  
**Promotes / extends**: LoopRail design draft (normative architecture for
job-scoped rails; this RFC adds Rail Exec and user-defined verb bodies)  
**Amended by**: RFC-232 (§9 — flat wire / nesting reject + optional slice
`depends_on`); IG-728 implements §10 LLM auto-pick

## Abstract

LoopRail is the job-scoped, event-driven workflow pattern system for Autopilot:
YAML rails declare **when** orchestration should act; a rail-agnostic runtime
applies **what** to the ContextEngine goal DAG. This RFC formalizes that
architecture and specifies **Rail Exec**: catalog verbs invoked by `flow` /
`rules` are recipes whose bodies are composed of **CE primitives (verbs)**
and/or **natural-language briefs/intent**, not hardcoded Python special cases
per `rail_id`. Custom rails under the three-tier catalog can reach the same
power as shipped builtins (including **streaming slice fan-out** and host
worktree merge) without forking the executor.

**Layering (normative):** LoopRail is consumed only by AutopilotService. The
Context Engine never reads rail YAML. CE goals execute in streaming parallel
under pool concurrency and `depends_on` readiness — with **no wave or stage
execution boundary** in CE.

## 1. Problem

v1 LoopRail shipped with the right *split* (YAML when / CE builtins what) but
power concentrated in:

1. A **closed** `then:` vocabulary (`CE_RAIL_BUILTINS`) implemented as large
   `_do_*` methods in `RailBuiltinExecutor`.
2. **Hardcoded** goal briefs, tags, and DAG shapes inside those methods.
3. Occasional **`rail_id` branches** (e.g. migration planner copy) that make the
   runtime rail-specific.
4. **Name-magic structural guards** keyed to condition names that encode
   greenfield semantics — reusable only by copying those names.

Teams can drop a custom rail YAML today, but cannot match greenfield/migration
power without editing host Python. That violates the design goal that project
rails (`.soothe/rails/`) override and extend builtins via catalog precedence
alone.

## 2. Goals

1. **Promote** LoopRail as the normative Autopilot workflow-pattern layer
   (event → guard → verb → CE DAG), aligned with RFC-222 / RFC-230 invariants.
2. Introduce **Rail Exec**: a rail-agnostic interpreter of catalog verb bodies.
3. Allow each catalog verb body to be defined as **verbs (L0 primitives)**,
   **NL** (brief / intent), or **hybrid** — data in rail YAML, not `rail_id`
   switches in Python.
4. Keep **CE primitives closed** and framework-owned (atomicity, resume, trace).
5. Preserve **fan-out as rail policy** (`fanout:` + flat WavePlan into a
   **slice catalog** on job state). Autopilot grows the CE DAG by spawning
   makers when slice deps are satisfied (**streaming spawn**). The engine
   remains wave-/stage-agnostic (deps + capacity clamp only). Wave/stage
   counters MUST NOT gate CE readiness.
6. Enable custom rails to reach **builtin-class power** (streaming slice
   fan-out, host worktree merge/refresh/land, feedback chains,
   domain-specific planner/review/QA copy) via YAML overrides.
7. **Host-manage worktrees**: on maker success, merge into per-job branch
   `job/<id>`; refresh peer worktrees; conflict → focused resolve goal;
   land on `main`/`master` only at job completion. Per-maker review/QA
   replace batch wave-integrate gates.
8. When submit omits `rail_id`, optionally **auto-pick** a rail via structured
   light-LLM match against the merged catalog (`summary` / `applies_when`),
   with deterministic fallbacks (RFC-630; design draft
   `2026-08-08-llm-rail-auto-pick-design.md`).

## 3. Non-goals

- Arbitrary Python, shell, or unconstrained scripts inside rail YAML.
- StrangeLoop learning DAG shape, siblings, or rail recipes (RFC-222).
- Engine-level wave/stage API or submit kwargs for slice lists (IG-715
  boundary). CE MUST NOT grow wave fields on goals.
- Replacing AutopilotMonitor dreaming / backoff for **no-rail** jobs.
- Visual rail editor.
- Per-rail prune-policy overrides beyond composing L0 `prune` / `replant`.
- Keyword/regex content judgment for guards, NL expand, or **rail selection**
  (RFC-630).
- LLM choosing next catalog verbs / flow advancement (report-commit judge and
  LoopRail remain separate — RFC-204).
- Re-picking `rail_id` mid-job (resume uses stored id + integrity).
- Nested WavePlan trees as machine contract (RFC-232).
- Requiring batch “wave complete → integrate” before other ready slices may
  exist in the CE DAG.

## 4. Architectural invariant

> **StrangeLoop executes one goal and always writes a ledger report. CE commits
> the report. AutopilotService judges on `goal_report_committed` (RFC-204 §1.3)
> — accept / send_back / fail + bounded DAG revise. LoopRail decides *when*
> (deterministic YAML). Rail Exec applies catalog verb recipes as CE
> primitives. AutopilotService also schedules workers and runs job maturity
> (RFC-230).**

```text
StrangeLoop loop end → CE commit_goal_report → goal_report_committed
  → Autopilot report-commit judge (accept | send_back | fail [+ bounded dag_ops])
  → job event (goal_completed | goal_send_back | goal_failed | dag_idle | …)
  → LoopRailInterpreter: match flow/rules + guards
  → Rail Exec: resolve verb body (rail override ▸ builtin default)
  → expand NL intent once (optional) → ActionPlan of L0 ops
  → execute L0 batch against ContextEngine + RailJobState
  → append rail_trace (verb + expanded steps + created goals)
```

Rail-bound jobs spawn follow-up goals **only** through Rail Exec (RFC-230
rail exclusivity). Monitor/verifier must not invent phases on rail jobs.
The report-commit judge MUST NOT select next catalog verbs — only the
verdict + allowlisted soft DAG ops (pending briefs, deps, priority).

## 5. Layer model

```text
L2  Flow / rules     event + when + then: <catalog_verb>
L1  Catalog verbs    named recipes (plan_milestones, spawn_wave_makers, …)
L0  CE primitives    closed ops (spawn_goal, wire_deps, foreach, …)
```

| Layer | Author | Mutates DAG? |
|-------|--------|--------------|
| L2 | Rail YAML (any catalog tier) | No — selects verb |
| L1 | Builtin defaults + optional `verbs:` override in rail YAML | Via L0 only |
| L0 | Framework Python (optional future plugin primitives) | Yes |

### 5.1 L0 CE primitives (normative closed set)

Atomic host/CE operations. Catalog validation rejects unknown op names in verb
bodies.

| Primitive | Behavior |
|-----------|----------|
| `spawn_goal` | `create_goal` + annotate tags/role/branch; optional workspace |
| `wire_deps` | Update `depends_on` / root-waits-on children (never child→root) |
| `foreach` | Iterate slice-catalog entries or an explicit list; bind loop vars |
| `ensure_worktree` | Optional git worktree under job policy (from `job/<id>` tip) |
| `ingest_wave_plan` | Architecture findings → `RailJobState` **slice catalog** |
| `merge_into_job_branch` | Host-merge maker branch into `job/<id>`; refresh peer WTs |
| `land_job_branch` | Host-merge `job/<id>` into configured base (`main`/`master`) |
| `gate` | Skip recipe when counter/acceptance/inflight predicates fail |
| `bump` | Increment job counters (`feedback_round`, optional budgets) |
| `prune` / `replant` | Branch salvage with `informs` (RFC-204 recovery) |
| `pause_job` | Suspend for human (`pause_for_user`) |
| `complete_job` | Mark job root complete when maturity allows (RFC-230) |

WavePlan **slice lists** are applied into `RailJobState` as a **flat slice
catalog** (SoT). Transfer may use structured completion fields, recommended
dumps, allowlist paths, or findings/evidence JSON — never nested wave trees,
NL inventing slices at exec time, or rigid rail `default_modules` (already
rejected by catalog). Wire shape, optional per-slice `depends_on`, and
nesting reject rules: [RFC-232](RFC-232-waveplan-flat-semistructured-ingest.md).

### 5.2 L1 catalog verbs

Names referenced by `then:`. Builtin rails ship default bodies. A rail document
MAY override or add verbs under `verbs:`.

Load-time rule: every `then:` must resolve to a builtin default recipe **or**
a `verbs:` entry on the winning rail document. Unknown names → catalog error
(same fail-fast as today's closed set).

Shipped recipe names (initial set; may grow as defaults, not as Python forks):

`decompose_parallel`, `plan_and_implement`, `plan_milestones`,
`spawn_wave_makers` (streaming **spawn-ready** semantics — §9),
`spawn_integrate` (**deprecated** for greenfield merge path; custom rails may
still compose it), `commit_milestone` (optional evidence helper; not a wave
barrier), `spawn_feedback_cycle`, `review`, `qa_verify`, `retry_branch`,
`retry_maker`, `retry_architecture`, `merge_branches` (host merge primitive),
`pause_for_user`, `complete_job`, `land_job_branch`.

### 5.3 L2 flow / rules

Unchanged semantics from the LoopRail draft:

- Events: `job_start`, `goal_completed`, `goal_failed`, `goal_blocked`,
  `goal_send_back`, `dag_idle`, `worker_timeout`, `user_intervention`.
- Guards: LLM-default structured `{ matched, confidence, reasoning }` (RFC-630);
  structural short-circuits as opt-in predicates (see §8).
- First matching rule wins unless `allow_multiple: true`.

## 6. Verb body modes

Each catalog verb resolves to a body. Bodies MUST use one of:

### 6.1 Hybrid (recommended default)

Structured L0 steps; NL only in goal briefs / intent fields.

```yaml
verbs:
  plan_milestones:
    do:
      - spawn_goal:
          role: planner
          tags: [architecture, planning, milestones]
          brief: |
            Architecture and milestone map for this job.
            REQUIRED: flat WavePlan JSON (wave_slices string list or flat
            slices[]); no nested waves/slices; dumps / wave_plan_path /
            completion blob OK — RFC-232 …
          wire: { root_waits_on: self }
```

### 6.2 Pure verb sequence

Deterministic recipes for multi-goal macros (today's `spawn_feedback_cycle`):

```yaml
verbs:
  spawn_feedback_cycle:
    do:
      - gate: { unless: acceptance_met, max: feedback_rounds, no_inflight: feedback }
      - bump: feedback_round
      - spawn_goal:
          id: diagnose
          role: diagnoser
          tags: [feedback, diagnose, "feedback-${feedback_round}"]
          brief: |
            Find bugs and acceptance gaps. Do not implement.
          depends: [trigger]
      - spawn_goal:
          id: optimize
          role: maker
          tags: [feedback, optimize, implementation, "feedback-${feedback_round}"]
          brief: |
            Fix against diagnose findings; minimal scope.
          depends: [diagnose]
      - spawn_goal:
          id: verify
          role: qa
          tags: [feedback, verify, qa, "feedback-${feedback_round}"]
          brief: |
            Re-run acceptance checks; report remaining gaps.
          depends: [optimize]
```

Interpolation is **template-only** (`${job_id}`, `${wave}`, `${feedback_round}`,
acceptance brief hooks) — not free keyword heuristics.

### 6.3 Pure NL intent (optional advanced)

```yaml
verbs:
  plan_milestones:
    intent: |
      Spawn one architecture planner that requires a WavePlan JSON findings
      entry; do not implement product code; root waits on the planner.
```

Rail Exec MUST expand `intent` **once per invocation** via a structured light
LLM call into an **ActionPlan** whose `ops` are drawn only from the L0 set
(§5.1). Invalid / unknown ops → fail the builtin (trace `builtin_error`); do
not partially apply. Prefer hybrid/verb bodies for shipped builtins; use
intent primarily for distiller drafts and advanced authors.

**Forbidden:** re-expanding intent on every retry without an ActionPlan cache
key; NL that directly mutates the DAG without an ActionPlan.

## 7. Rail Exec

### 7.1 Responsibilities

| Concern | Owner |
|---------|-------|
| Resolve rail YAML + bind `fanout:` / counters | `LoopRailInterpreter.bind_job` |
| Match events → `then:` verb name | Interpreter |
| Resolve verb body (override ▸ default) | Rail Exec |
| Template interpolate / optional intent→ActionPlan | Rail Exec |
| Execute L0 batch; return `BuiltinResult` | Rail Exec |
| Persist `RailJobState`; append trace | Exec + trace store |

### 7.2 Resolution order

For verb `V` on job bound to rail `R`:

1. `R.verbs[V]` if present on the winning catalog document.
2. Else package builtin recipe for `V` (shipped with `soothe`).
3. Else error (`unknown builtin` / load-time validation for `then:`).

No `if state.rail_id == "…"`. Domain differences (migration vs greenfield
planner copy) live entirely in YAML bodies.

### 7.3 Trace

Each fire records at least:

- `rule_id`, `event`, guard result
- catalog `verb` name
- expanded L0 step summaries (op name + created goal ids)
- `builtin_result` status / detail

Trace remains append-only and job-scoped (draft §7 / existing `rail_trace`).

### 7.4 Atomicity

A single verb invocation is one logical batch: either the ActionPlan commits
or the invocation errors without partial DAG commit (same contract as draft
§12 for CE builtin failure). `prune`+`replant` recovery rules from the draft
and RFC-204 / IG-693 still apply.

## 8. Guards and structural predicates

### 8.1 Shared vocabulary

Shared structural short-circuit vocabulary (structural-fact based, not
rail-id based). **Normative for streaming greenfield / migration fan-out:**

| Name | Structural intent |
|------|-------------------|
| `architecture_ready` | Architecture terminal; catalog non-empty when `require_plan`; ready unspawned slices may exist |
| `slices_ready_to_spawn` | At least one catalog slice unspawned whose slice deps are satisfied |
| `maker_merged` | A maker completed and host-merged into `job/<id>` (triggers per-maker quality) |
| `needs_review` / `needs_qa` | Per-lineage (merged maker range), not “wave complete” |
| `needs_feedback` | Lineage QA/acceptance gap (RFC-230 maturity still feeds job-level acceptance) |
| `architecture_failed` | Planner failed / no usable catalog |
| `job_complete` | Acceptance + idle; ready for `land_job_branch` then `complete_job` |

**Deprecated as execution barriers** (MUST NOT gate whether slice makers exist
in the CE DAG): `wave_makers_done`, `ready_for_next_wave`, `needs_integrate`
as batch wave integrate. Custom rails MAY keep the names with non-barrier
semantics during migration; shipped greenfield MUST NOT use them to withhold
ready slices.

### 8.2 Evolution (preferred)

Rails MAY declare structural hooks beside NL conditions:

```yaml
conditions:
  architecture_ready:
    nl: |
      The architecture / milestone map completed and the slice catalog is ready;
      streaming spawn may create ready makers.
    structural:
      require: [architecture_terminal, wave_plan_if_required]
  slices_ready_to_spawn:
    nl: |
      At least one catalog slice is unspawned and its slice deps are satisfied.
    structural:
      require: [catalog_has_ready_unspawned]
```

Predicate ids are a closed library owned by the host (rail-agnostic). Unknown
predicate → load-time error. NL remains the human/LLM-facing description;
structural block is the deterministic short-circuit when present.

RFC-230 maturity fields (`acceptance_met`, snapshot) continue to feed
`needs_feedback` / `job_complete` predicates.

## 9. Fan-out contract (streaming slice catalog)

Design source:
[`2026-08-08-streaming-slice-dag-worktree-lifecycle-design.md`](../drafts/2026-08-08-streaming-slice-dag-worktree-lifecycle-design.md).

### 9.1 Layer ownership

| Layer | Owns | Must not |
|-------|------|----------|
| Autopilot engine | Pool, CE `depends_on`, report-commit judgment, `max_parallel_goals` clamp | Slice ids, wave/stage phase order, rail YAML |
| Context Engine | Goal DAG status and edges | Rail documents, wave index, slice catalog |
| Rail YAML | `flow` / conditions / `fanout` / `verbs` | Submit kwargs for slices; nested WavePlan examples; `fanout.artifact`; wave barriers that withhold ready slices |
| LLM + transfer | Flat WavePlan (+ optional per-slice `depends_on`) via structured fields, dumps, allowlist, or completion blob | Nested waves/slices |
| LoopRail / AutopilotService | Ingest catalog; **streaming spawn**; host merge/refresh/land; per-maker review/QA reactions | Store nested wave trees; teach CE about waves |

### 9.2 Slice catalog SoT

**Persistence (normative; amends IG-720 via multi-form transfer):**

1. **SoT** after ingest is the **slice catalog** on `RailJobState` (persisted in
   `rail_state.json`): flat leaf specs derived from `wave_slices` and/or rich
   `slices[]` (RFC-232). Compatible on-disk keys may still expose
   `wave_slices` / `decompose_plan` as the flattened id list + rich specs.
   Optional `wave_plan_source_path` records which file supplied the plan.
2. Catalog entries: `{slice, description?, tags?, priority?, depends_on?}`.
   Omitted `depends_on` ⇒ ready after architecture (true fan-out).
3. Additional runtime maps (normative): `spawned_slices` (`slice_id → goal_id`),
   `job_branch` (e.g. `job/<id>`), `base_branch` (`main` or `master`).
4. Architecture / planner goals supply a **flat** WavePlan via any transfer
   form (unchanged multi-form list). Host **rejects nested waves/slices**,
   validates, then `record_wave_plan` applies the catalog. Gate send_backs
   MUST include reject / validation detail (RFC-232).
5. `is_wave_plan_ready` / catalog-ready is true when the catalog has at least
   one leaf slice (or multi-form diagnose still yields a **flat** WavePlan).
6. **`wave_index` / batch `wave_slices` rounds MUST NOT gate spawn.** Optional
   expansion budget `max_slices` (alias: legacy `fanout.max_waves`) may cap
   total makers; it is not a stage barrier.

`fanout:` keys: `require_plan`, `scout_count`, `max_slices` (preferred;
`max_waves` accepted as alias). `fanout.artifact` remains **removed**. Rails
without `fanout:` must not pollute job state with wave-plan requirements.

### 9.3 Streaming spawn (normative)

Catalog verb `spawn_wave_makers` (name stable for custom rails) implements
**spawn-ready** semantics:

1. On `architecture_ready` and on subsequent `goal_completed` / `dag_idle`
   when `slices_ready_to_spawn`: create maker goals only for **unspawned**
   slices whose `depends_on` slice ids map to **completed** maker goals (or
   have no deps).
2. Maker CE `depends_on`: architecture goal + CE goals for satisfied slice
   deps. Children MUST NEVER `depends_on` the job root while it is active.
3. Root coordinator waits on spawned makers (and later land), unchanged
   pattern.
4. Pool fills streaming: when a maker completes and a slot frees, any other
   **CE-ready** goal (including newly spawned makers) may claim it.
5. Shipped greenfield/migration MUST NOT wait for batch integrate / “wave
   done” before materializing other ready catalog slices.

### 9.4 Host worktree lifecycle (normative)

When `worktrees_enabled` (default true for greenfield-class rails):

1. Ensure `job_branch` from `base_branch` at first maker spawn (or earlier).
2. Each maker gets an isolated worktree + branch from the current `job_branch`
   tip (`ensure_worktree`).
3. On **maker success**: host `merge_into_job_branch` (catalog
   `merge_branches` / L0). On success, refresh/rebase other **active** maker
   worktrees onto the new tip; annotate maker `branch_status=merged`.
4. On **merge conflict**: do **not** suspend the job. Annotate conflict;
   spawn a focused **resolve** goal on that lineage; siblings keep running.
   Retry host merge after resolve completes.
5. Maker briefs MUST NOT say “leave commits for later integrate”; they MUST
   state that the host merges into `job_branch` on completion.
6. **Final land**: on `job_complete`, `land_job_branch` merges `job_branch`
   into `base_branch`, then `complete_job`. Mid-job `base_branch` is not the
   integration tip.

Batch agent `spawn_integrate` is **not** the greenfield merge path. Custom
rails may still spawn an integrate-style goal for audit, but MUST NOT use it
to withhold ready slice spawn.

### 9.5 Per-maker quality chain

After a successful host merge of maker M:

1. Rail MAY spawn diff-scoped `review` then `qa_verify` for M’s land range /
   slice tags (`maker_merged` / `needs_review` / `needs_qa`).
2. Feedback cycles attach to **that lineage** when QA/acceptance fails.
3. These quality goals MUST NOT appear in `depends_on` of unrelated ready
   makers (they must not serialize the streaming DAG).

## 10. Catalog storage and selection

Three-tier precedence (low → high, last wins), unchanged:

1. `packages/soothe/src/soothe/autopilot/rails/builtin_rails/`
2. `$SOOTHE_HOME/rails/`
3. `<workspace>/.soothe/rails/`

Drafts under `drafts/` are never loaded. There is no invented `default.yml`.

### 10.1 Selection cascade

On job submit (root goal only; `parent_id is None`):

```text
1. Explicit rail_id / --rail
      → must exist in merged catalog; unknown id rejects submit
2. If agent.autopilot.rail_auto_pick and a picker model is available:
      structured light-LLM over filtered catalog candidates
        → rail_id in allowed ∧ confidence ≥ min → bind that rail
        → rail_id null ∧ confidence ≥ min ∧ abstain_overrides_defaults
            → no rail (skip steps 3–4)
        → else (low confidence / invalid id / timeout / error)
            → continue to step 3
3. Workspace <workspace>/.soothe/rails/.rail-default (first non-comment line)
4. agent.autopilot.default_rail
5. No rail — Monitor/CE opportunistic path
```

Optional `rail_auto_pick_skip_if_workspace_default`: when true and
`.rail-default` exists, skip step 2 and use the marker (operator-pinned
workspace). Default false (LLM first; marker is fallback).

Resolution MUST complete **before** LoopRail bind / `job_start`. Auto-pick
failure MUST NOT fail submit solely for that reason — degrade to steps 3–5.

Sync helper `resolve_rail_id` remains the deterministic subset (explicit →
workspace default → config → none) for tests and when auto-pick is off.

### 10.2 LLM auto-pick (RFC-630)

When step 2 runs:

- **Candidates**: `LoopRailCatalog(workspace).load_all()` after excluding rails
  with `auto_pick: false` (e.g. shipped `greenfield-system`) and any ids in
  `rail_auto_pick_deny` (operator extras; default empty). Builtins and
  external home/workspace rails share one list; last-wins merge already applied.
- **Card fields only**: `id`, truncated `summary`, truncated `applies_when`
  (optional `version` / source tier for logs). Do not send `flow` / `verbs` /
  full YAML.
- **Caps**: truncate NL fields; if candidate count exceeds
  `rail_auto_pick_max_candidates`, skip LLM and use steps 3–5 (fail closed —
  do not silently drop arbitrary rails).
- **Prompt**: stable system policy (no hardcoded rail names or counts) + user
  message with generated Allowed ids, `<catalog_data>` cards, and job text in
  `<untrusted_data>`. Catalog NL is data about options; job text is the request
  to classify — neither is instructions (same posture as rail guards).
- **Output**: structured `{rail_id, confidence, reasoning}`. Host validates
  `rail_id ∈ allowed ∪ {null}`.
- **Model**: `rail_auto_pick_model_role` or fallback `monitor_model_role`.
- **Persistence**: record `source`, `confidence`, `reasoning`,
  `candidates_considered`, and a catalog hash on job metadata /
  `rail_state.json` for forensics.

Auto-pick MUST NOT choose next flow verbs. It only sets root `rail_id` once.

Implementation: [IG-728](../impl/IG-728-llm-rail-auto-pick.md). Design detail:
[2026-08-08-llm-rail-auto-pick-design.md](../drafts/2026-08-08-llm-rail-auto-pick-design.md).

### 10.3 Validity

A rail is valid iff removing it changes outcomes vs no-rail for the same submit
text. `applies_when` / `summary` SHOULD be self-contained (no “better than X”
rankings) so external catalog updates remain first-class for auto-pick.

## 11. Migration from v1 Python builtins

Incremental, behavior-preserving:

| Phase | Work | Exit criteria |
|-------|------|---------------|
| **M1** | Extract current `_do_*` into builtin recipe YAML; Rail Exec runs them; Python becomes adapters or deleted | Existing rail tests green; no behavior change |
| **M2** | Allow rail YAML `verbs:` overrides (briefs/tags first) | Remove `rail_id == "migration"` (and similar); migration/greenfield differ by YAML only |
| **M3** | Allow multi-step `do:` overrides on workspace rails | Custom feedback/planner chains without new closed verbs |
| **M4** | Optional `intent:` → ActionPlan for distiller / advanced authors | Schema validation + L0 allowlist; tests for reject paths |

Until M1 lands, the **normative user-facing contract** of this RFC (flow,
events, catalog verbs, fanout, rail exclusivity, maturity hooks) already
matches shipped code; M2–M4 are the Exec optimization.

**Progress:** [IG-716](../impl/IG-716-rail-exec-verb-briefs.md) landed M2 brief/
tags/role overrides + host default briefs (M1 skeleton).
[IG-717](../impl/IG-717-rail-exec-do-recipes.md) landed M3 `do:` L0 recipes
(subset: spawn_goal / wire_deps / gate / bump / pause_job / complete_job);
`plan_milestones` on greenfield/migration uses `do:`. Remaining: foreach /
worktree / feedback macro extract; **M4** intent expand.

## 12. Error handling

| Failure | Behavior |
|---------|----------|
| Unknown `then:` / unknown L0 op in body | Load-time catalog error |
| Intent expands to non-L0 op | Builtin error; no partial apply |
| CE / L0 failure mid-batch | Trace `builtin_error`; no partial DAG commit |
| Guard LLM timeout | Log; skip rule; optional deterministic `check:` fallback |
| WavePlan / catalog missing when `require_plan` | Structural gate does not match; makers do not spawn |
| Nested WavePlan (waves/slices trees) | Architecture gate `send_back` with nesting reason; no apply (RFC-232) |
| Host merge conflict on maker success | Resolve goal on lineage; siblings continue; no job-wide pause |
| Peer worktree refresh fails (dirty) | Annotate that WT; optional resolve; other makers unaffected |
| Final land conflict | Land-resolve goal; do not `complete_job` until land succeeds |
| Consensus send-back exhausted (rail subgoal) | Subgoal `failed` + `goal_failed`; recipe recovery (e.g. `retry_maker`) — RFC-204 / IG-693 |
| Auto-pick low confidence / timeout / error | Fall back to `.rail-default` / config / no rail; log reasoning |
| Auto-pick returns unknown or denied id | Treat as picker failure → same fallback |
| Auto-pick high-confidence abstain | No rail when `abstain_overrides_defaults`; else continue fallback ladder |
| Candidate set exceeds max | Skip LLM → deterministic fallback |

## 13. Testing strategy

| Layer | Coverage |
|-------|----------|
| Recipe schema | Parse hybrid/verb/intent bodies; reject unknown L0 |
| Catalog | Project overrides builtin same id; `verbs:` merge rules |
| Rail Exec | Builtin default bodies ≡ current `_do_*` golden DAG shapes |
| Overrides | Migration brief override without `rail_id` branch |
| Intent expand | Valid ActionPlan applied; invalid ops rejected |
| Guards | Structural predicates + RFC-230 maturity |
| Trace | Expanded L0 steps recorded |
| Resume | Incomplete prune/replant recovery unchanged |
| Auto-pick | Cascade order; unknown id; deny/`auto_pick: false`; formatter with N custom rails; timeout → fallback; bind before `job_start` |
| Streaming spawn | Independent slices parallel under cap; dep edge delays spawn until predecessor **merged/completed**; no wave barrier |
| Worktree merge | Maker tip lands on `job/<id>`; peer WT refresh; conflict → resolve; final land on base |

## 14. Component map

| Module | Path |
|--------|------|
| Catalog + `RailDefinition` | `soothe/autopilot/rails/catalog.py` |
| Path tiers | `soothe/autopilot/rails/builtins.py` |
| Builtin / override recipes | `soothe/autopilot/rails/builtin_rails/*.yml` + `verbs:` |
| Rail selection / auto-pick | `soothe/autopilot/rails/selector.py` (+ picker helper) |
| Interpreter (L2) | `soothe/autopilot/rails/interpreter.py` |
| Rail Exec (L1→L0) | `soothe/autopilot/rails/` (evolve `builtins_exec.py` → exec + primitives) |
| Guards | `soothe/autopilot/rails/guards.py` |
| WavePlan | `soothe/autopilot/rails/wave_plan.py` |
| Trace | `soothe/autopilot/rails/trace_store.py` |
| Submit bind | `soothe/autopilot/service.py` (`submit_goal` → resolve → `_bind_rail_for_job`) |
| Protocol reference | `soothe_nano` skill `looprail-creator` references |

## 15. Decision log

| Topic | Decision |
|-------|----------|
| Promote LoopRail draft | Yes — this RFC is normative for rails + Exec |
| User surface for power | YAML verb bodies (verbs \| NL \| hybrid), not per-rail Python |
| L0 ownership | Framework-closed; optional future primitive plugins only |
| NL in bodies | Briefs + optional once-per-fire intent→ActionPlan (RFC-630) |
| `rail_id` switches in Exec | Forbidden after M2 |
| Fan-out / engine boundary | Fan-out = rail policy; engine/CE wave-agnostic (IG-715); **no wave execution barrier** |
| Streaming spawn | Grow CE DAG as slice deps satisfied; pool streams ready goals |
| Worktree merge | Host merge into `job/<id>` on maker success; land on main/master at job complete |
| Quality gates | Per-maker review/QA after merge; not batch wave integrate |
| Merge conflict | Lineage resolve goal; job not suspended |
| WavePlan persistence | SoT = slice catalog on `RailJobState`; transfer via structured fields, dumps, allowlist, or findings blob (IG-722 amends IG-720) |
| WavePlan wire shape | Flat leaf slices + optional `depends_on`; semi-structured allowed; **nested waves/slices forbidden** (RFC-232) |
| New `then:` without L0 | Forbidden — compose L0 or add framework primitive |
| Default body style for builtins | Hybrid |
| Rail selection without `--rail` | Structured LLM auto-pick over dynamic catalog, then `.rail-default` / config / none (IG-728) |
| Auto-pick prompt | Stable system + live candidate cards; no hardcoded builtin list |
| `greenfield-system` auto-pick | YAML `auto_pick: false`; still selectable via explicit `--rail` |

## 16. Open questions

- Exact ActionPlan JSON schema versioning and cache key for intent expand.
- Whether `flow.then` may be a list of catalog verbs in one hook (draft open Q).
- Structural predicate library completeness vs keeping name-magic forever.
- Plugin registration surface for new L0 primitives (defer until a concrete need).
- Whether workspace-tier rails should be ordered before builtins in the auto-pick
  prompt (default: alphabetical by id for stability).
- Peer worktree refresh default: rebase vs merge-from-`job_branch`.
- Short vs full job id in `job/<id>` branch names (today often `job_id[:8]`).
- Opportunistic GC of worktrees for cancelled/completed foreign jobs.

## 17. Suggested implementation routing

1. IG for **M1–M2** (recipe extraction + brief overrides; delete rail_id forks)
   → **IG-716** (implemented: briefs/tags/role; full recipe extract deferred).
2. Follow-on IG for **M3** multi-step `do:` → **IG-717** (implemented L0 subset;
   wave/feedback macros still Python). **M4** intent expand still open.
3. **IG-718** Slice terminology hard cut (`wave_slices` / `slices`; no module
   wire keys).
4. **IG-720** Remove filesystem WavePlan artifact; CE findings + rail_state only
   (transfer forms restored/amended by IG-722; SoT remains job rail state).
5. Update `looprail-protocol.md` and builtin rail README to document `verbs:`.
6. **RFC-232** + follow-on IG: flat WavePlan wire ingest, nesting reject,
   actionable architecture-gate send_backs; amend §9 briefs.
7. **IG-722** Multi-form WavePlan transfer (structured path/blob, recommended
   dumps, allowlist); SoT = `RailJobState`.
8. **IG-728** LLM rail auto-pick (§10.1–10.2): picker, cascade, config, tests;
   align builtin README.
9. **IG-732** (Draft): streaming slice DAG + host worktree lifecycle —
   slice catalog + spawn-ready; host `merge_branches` / merge-on-success /
   refresh / land; greenfield + migration YAML rewrite; per-maker review/QA;
   tests from §13. Design draft:
   `docs/drafts/2026-08-08-streaming-slice-dag-worktree-lifecycle-design.md`.

## Appendix A: relation to prior docs

| Document | Relation |
|----------|----------|
| `docs/drafts/2026-07-11-loop-rail-design.md` | Earlier design notes; this RFC is normative for rails + Rail Exec |
| `docs/drafts/2026-08-08-llm-rail-auto-pick-design.md` | LLM auto-pick design; §10 is normative; IG-728 implements |
| RFC-230 | Maturity latch + rail exclusivity; consumes Exec outcomes |
| RFC-204 | Report-commit judgment / send-back; host recovery via catalog verbs |
| RFC-222 / RFC-625 | Autopilot / CE ownership; StrangeLoop report → CE commit before rail events |
| `2026-08-08-autopilot-report-commit-judgment-design.md` | Event-centric judgment; bounded DAG revise; deterministic rail |
| RFC-232 | Flat WavePlan wire; optional slice `depends_on`; nesting forbidden; amends §9 |
| `2026-08-08-streaming-slice-dag-worktree-lifecycle-design.md` | Streaming spawn + host worktree lifecycle; source for §9 revision |
| IG-715 | Migration fan-out; planner copy into YAML bodies (M2); wave barriers to remove |
| IG-720 | Historical findings-only file ban; amended by IG-722 (SoT still rail_state) |
| IG-722 | Multi-form WavePlan transfer; recommended dumps + structured wave_plan_path |
| IG-728 | LLM rail auto-pick on submit when `rail_id` omitted |
