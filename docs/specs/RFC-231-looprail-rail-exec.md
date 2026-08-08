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
design draft `docs/archive/drafts/2026-08-08-autopilot-report-commit-judgment-design.md`,
IG-678, IG-687, IG-691, IG-692, IG-693, IG-700, IG-704, IG-714, IG-715, IG-720,
IG-728 (LLM rail auto-pick)  
**Promotes / extends**: LoopRail design draft (normative architecture for
job-scoped rails; this RFC adds Rail Exec and user-defined verb bodies)  
**Amended by**: RFC-232 (§9 Fan-out contract — flat wire / nesting reject);
IG-728 implements §10 LLM auto-pick

## Abstract

LoopRail is the job-scoped, event-driven workflow pattern system for Autopilot:
YAML rails declare **when** orchestration should act; a rail-agnostic runtime
applies **what** to the ContextEngine goal DAG. This RFC formalizes that
architecture and specifies **Rail Exec**: catalog verbs invoked by `flow` /
`rules` are recipes whose bodies are composed of **CE primitives (verbs)**
and/or **natural-language briefs/intent**, not hardcoded Python special cases
per `rail_id`. Custom rails under the three-tier catalog can reach the same
power as shipped builtins (including wave fan-out) without forking the executor.

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
5. Preserve **fan-out as rail policy** (`fanout:` + WavePlan into job state);
   engine remains wave-agnostic (capacity clamp only).
6. Enable custom rails to reach **builtin-class power** (waves, feedback chains,
   domain-specific planner/review/QA copy) via YAML overrides.
7. When submit omits `rail_id`, optionally **auto-pick** a rail via structured
   light-LLM match against the merged catalog (`summary` / `applies_when`),
   with deterministic fallbacks (RFC-630; design draft
   `2026-08-08-llm-rail-auto-pick-design.md`).

## 3. Non-goals

- Arbitrary Python, shell, or unconstrained scripts inside rail YAML.
- StrangeLoop learning DAG shape, siblings, or rail recipes (RFC-222).
- Engine-level wave API or submit kwargs for slice lists (IG-715 boundary).
- Replacing AutopilotMonitor dreaming / backoff for **no-rail** jobs.
- Visual rail editor.
- Per-rail prune-policy overrides beyond composing L0 `prune` / `replant`.
- Keyword/regex content judgment for guards, NL expand, or **rail selection**
  (RFC-630).
- LLM choosing next catalog verbs / flow advancement (report-commit judge and
  LoopRail remain separate — RFC-204).
- Re-picking `rail_id` mid-job (resume uses stored id + integrity).

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
| `foreach` | Iterate WavePlan slices or an explicit list; bind loop vars |
| `ensure_worktree` | Optional git worktree under job policy |
| `ingest_wave_plan` | Architecture goal findings (CE) → `RailJobState` slices |
| `gate` | Skip recipe when counter/acceptance/inflight predicates fail |
| `bump` | Increment `wave_index` / `feedback_round` (etc.) |
| `prune` / `replant` | Branch salvage with `informs` (RFC-204 recovery) |
| `pause_job` | Suspend for human (`pause_for_user`) |
| `complete_job` | Mark job root complete when maturity allows (RFC-230) |

WavePlan **slice lists** are applied into `RailJobState` as a **flat** leaf
list (SoT). Transfer may use structured completion fields, recommended dumps,
allowlist paths, or findings/evidence JSON — never nested wave trees, NL
inventing slices at exec time, or rigid rail `default_modules` (already
rejected by catalog). Wire shape and nesting reject rules:
[RFC-232](RFC-232-waveplan-flat-semistructured-ingest.md).

### 5.2 L1 catalog verbs

Names referenced by `then:`. Builtin rails ship default bodies. A rail document
MAY override or add verbs under `verbs:`.

Load-time rule: every `then:` must resolve to a builtin default recipe **or**
a `verbs:` entry on the winning rail document. Unknown names → catalog error
(same fail-fast as today's closed set).

Shipped recipe names (initial set; may grow as defaults, not as Python forks):

`decompose_parallel`, `plan_and_implement`, `plan_milestones`,
`spawn_wave_makers`, `spawn_integrate`, `commit_milestone`,
`spawn_feedback_cycle`, `review`, `qa_verify`, `retry_branch`, `retry_maker`,
`retry_architecture`, `merge_branches`, `pause_for_user`, `complete_job`.

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

Existing structural short-circuit names (`architecture_ready`,
`wave_makers_done`, `needs_integrate`, `needs_commit`, `needs_review`,
`needs_qa`, `needs_feedback`, `ready_for_next_wave`, `architecture_failed`,
`job_complete`, …) remain a **documented shared vocabulary**. Any rail may use
them; semantics are structural-fact based, not rail-id based.

### 8.2 Evolution (preferred)

Rails MAY declare structural hooks beside NL conditions:

```yaml
conditions:
  architecture_ready:
    nl: |
      The architecture / milestone map completed and makers are not spawned yet.
    structural:
      require: [architecture_terminal, no_makers, wave_plan_if_required]
```

Predicate ids are a closed library owned by the host (rail-agnostic). Unknown
predicate → load-time error. NL remains the human/LLM-facing description;
structural block is the deterministic short-circuit when present.

RFC-230 maturity fields (`acceptance_met`, snapshot) continue to feed
`needs_feedback` / `job_complete` predicates.

## 9. Fan-out contract

| Layer | Owns | Must not |
|-------|------|----------|
| Autopilot engine | Pool, deps, report-commit judgment, `max_parallel_goals` clamp | Slice ids, `wave_index`, phase order |
| Rail YAML | `flow` / conditions / `fanout` / `verbs` | Submit kwargs for slices; nested WavePlan examples; `fanout.artifact` |
| LLM + transfer | Flat WavePlan via structured `wave_plan` / `wave_plan_path`, recommended dumps, allowlist paths, or completion JSON blob | Nested waves/slices |
| LoopRail | Apply parsed **flat** WavePlan into `RailJobState` (`wave_slices` / `decompose_plan`); persist via `rail_state.json`; optional `wave_plan_source_path` | Store nested wave trees on job state |

**Persistence (normative; amends IG-720 via multi-form transfer):**

1. **SoT** after ingest is `RailJobState.wave_slices` / `decompose_plan`
   (persisted in `rail_state.json`). Optional `wave_plan_source_path` records
   which file supplied the plan.
2. Architecture / planner goals supply a **flat** WavePlan via any transfer
   form: structured contribution fields (`wave_plan`, `wave_plan_path`),
   recommended dumps (`$SOOTHE_DATA_DIR/jobs/{job_id}/wave-plan.json`,
   `<workspace>/.soothe/wave-plan.json`), declarative allowlist paths, or a
   findings/evidence JSON blob. Custom paths outside the allowlist MUST set
   `wave_plan_path` (no prose path scraping).
3. Host extracts candidates, **rejects nested waves/slices** (no
   clever-flatten), validates, then calls `record_wave_plan` to **apply**
   leaf ids into `RailJobState`. Successful apply mirrors recommended dumps
   best-effort. Gate send_backs MUST include reject / validation detail
   (RFC-232).
4. `is_wave_plan_ready` is true when `RailJobState.wave_slices` is non-empty
   (or multi-form diagnose still yields a **flat** WavePlan).
5. Rail **wave rounds** (`wave_index` / `max_waves`) are job counters, not
   nested objects inside the WavePlan payload.

`fanout:` keys: `require_plan`, `scout_count`, `max_waves`. The former
`fanout.artifact` key remains **removed** (catalog reject; use structured
`wave_plan_path` or recommended dumps). Rails without `fanout:` must not
pollute job state with wave-plan requirements.

## 10. Catalog storage and selection

Three-tier precedence (low → high, last wins), unchanged:

1. `packages/soothe/src/soothe/rails/builtin_rails/`
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
| WavePlan missing when `require_plan` | Structural gate does not match; makers do not spawn |
| Nested WavePlan (waves/slices trees) | Architecture gate `send_back` with nesting reason; no apply (RFC-232) |
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

## 14. Component map

| Module | Path |
|--------|------|
| Catalog + `RailDefinition` | `soothe/rails/catalog.py` |
| Path tiers | `soothe/rails/builtins.py` |
| Builtin / override recipes | `soothe/rails/builtin_rails/*.yml` + `verbs:` |
| Rail selection / auto-pick | `soothe/rails/selector.py` (+ picker helper) |
| Interpreter (L2) | `soothe/autopilot/rail/interpreter.py` |
| Rail Exec (L1→L0) | `soothe/autopilot/rail/` (evolve `builtins_exec.py` → exec + primitives) |
| Guards | `soothe/autopilot/rail/guards.py` |
| WavePlan | `soothe/autopilot/rail/wave_plan.py` |
| Trace | `soothe/autopilot/rail/trace_store.py` |
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
| Fan-out / engine boundary | Unchanged (IG-715) |
| WavePlan persistence | SoT = `RailJobState`; transfer via structured fields, recommended dumps, allowlist, or findings blob (IG-722 amends IG-720) |
| WavePlan wire shape | Flat leaf slices only; semi-structured markdown+JSON allowed; **nested waves/slices forbidden** (RFC-232) |
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

## Appendix A: relation to prior docs

| Document | Relation |
|----------|----------|
| `docs/drafts/2026-07-11-loop-rail-design.md` | Earlier design notes; this RFC is normative for rails + Rail Exec |
| `docs/drafts/2026-08-08-llm-rail-auto-pick-design.md` | LLM auto-pick design; §10 is normative; IG-728 implements |
| RFC-230 | Maturity latch + rail exclusivity; consumes Exec outcomes |
| RFC-204 | Report-commit judgment / send-back; host recovery via catalog verbs |
| RFC-222 / RFC-625 | Autopilot / CE ownership; StrangeLoop report → CE commit before rail events |
| `2026-08-08-autopilot-report-commit-judgment-design.md` | Event-centric judgment; bounded DAG revise; deterministic rail |
| RFC-232 | Flat WavePlan wire; semi-structured allowed; nesting forbidden; amends §9 |
| IG-715 | Migration wave fan-out; must migrate planner copy into YAML bodies (M2) |
| IG-720 | Historical findings-only file ban; amended by IG-722 (SoT still rail_state) |
| IG-722 | Multi-form WavePlan transfer; recommended dumps + structured wave_plan_path |
| IG-728 | LLM rail auto-pick on submit when `rail_id` omitted |
