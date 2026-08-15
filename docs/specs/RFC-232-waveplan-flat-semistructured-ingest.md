# RFC-232: Flat WavePlan Wire Ingest (Semi-Structured, No Nesting)

**RFC**: 232
**Title**: Flat WavePlan Wire Ingest (Semi-Structured, No Nesting)
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-08-07
**Updated**: 2026-08-08
**Authors**: Soothe Team
**Depends on**: RFC-231, RFC-204, RFC-222, RFC-625, RFC-630
**Related**: RFC-230,
design draft `docs/drafts/2026-08-08-streaming-slice-dag-worktree-lifecycle-design.md`,
design draft `docs/archive/drafts/2026-08-08-autopilot-report-commit-judgment-design.md`,
IG-704, IG-714, IG-718, IG-720, IG-722
**Amends**: RFC-231 §9 (Fan-out contract — streaming slice catalog)

## Abstract

Architecture goals on `require_plan` rails must deliver a **flat** WavePlan that
the host applies into `RailJobState` as a **slice catalog** (flattened
`wave_slices` / rich `decompose_plan` / `slices[]`). This RFC tightens the
**wire contract**: completion evidence MAY be semi-structured (markdown prose
plus one JSON block), but the **canonical plan is always a flat list of leaf
slice specs** — never nested waves, never nested slices. Rich leaves MAY
declare optional `depends_on: [slice_id, …]` so Autopilot can **stream-spawn**
makers into the CE DAG as deps clear (RFC-231 §9). Transfer may also use
recommended dumps or structured `wave_plan_path` (IG-722); SoT after apply
remains job rail state.

It addresses production thrash where planners invent `WAVE-0 → {slices:[…]}`
trees (or write `docs/architecture/*.json`) and fail the deterministic
architecture WavePlan gate until send-back budget exhaustion.

## 1. Problem

IG-720 made CE completion findings + `RailJobState` the sole SoT and removed
`wave-plan.json`. That fixed dual-SoT confusion but left a brittle ingest path:

1. **Strict bare JSON** — host expects `WavePlan` pydantic shape in findings /
   evidence; agents often emit custom “wave schedule” JSON.
2. **Nested wave trees** — e.g. `wave_slices` as a dict keyed by `WAVE-*`, or a
   list of wave objects each containing inner `slices`. These fail validation
   (`list[str]` / flat `slices[]`) and are the wrong product for fan-out.
3. **Opaque send-backs** — generic “bare WavePlan required” text omits pydantic
   field errors, so rework loops bootstrap and re-emit the same invalid shape.
4. **File transfer thrash** — agents wrote large markdown/JSON under the
   project tree while the gate only accepted wire JSON (addressed by
   IG-722 multi-form transfer; SoT remains job state).

Fan-out needs **leaf ownership units** plus optional **slice→slice edges** for
streaming `spawn_wave_makers` (spawn-ready). Rail **must not** encode execution
stages as nested objects inside the plan. Optional expansion budget
(`max_slices` / legacy `max_waves`) is a scalar cap, not a nested schedule.

## 2. Goals

1. **Flat-only canonical plan** — `wave_slices: list[str]` and/or flat
   `slices: [{slice, description?, priority?, tags?, depends_on?}]`. No
   hierarchy.
2. **Optional slice deps** — `depends_on` lists peer **slice ids** (not goal
   ids). Omitted ⇒ ready after architecture. Host maps ids → CE goals at spawn
   time (RFC-231 §9.3).
3. **Semi-structured wire allowed** — markdown rationale + one JSON block (or a
   dedicated structured completion field) is acceptable input to ingest.
4. **Reject nesting** — nested waves/slices MUST fail closed (send_back / no
   apply); do **not** “clever-flatten” WAVE trees into job state.
5. **SoT = job state** — applied catalog lives on `RailJobState`; persist via
   `rail_state.json`. Transfer may use dumps / structured path / findings
   blob (IG-722); files are never a second live SoT after apply.
6. **Actionable gate failures** — send_back reasoning MUST include the first
   validation / nesting reject reason (field path + short message).
7. **Optional flat coerce** — host MAY normalize *flat* malformations only
   (see §5.3); never invent slice lists from prose keywords (RFC-630).

## 3. Non-goals

- Restoring filesystem WavePlan SoT (`fanout.artifact`, workspace scrape).
- Nano/agent tools that call Autopilot `record_wave_plan` (host-owned ingest).
- Nested wave schedules, milestone DAGs, or multi-level slice trees as machine
  contract (prose markdown may *describe* phases; job state must not store them).
- Replacing the deterministic architecture gate with free-form LLM consensus
  when `require_plan` is true.
- Teaching CE about waves; wave/stage fields on goals.
- Requiring `depends_on` on every slice (default remains parallel after
  architecture).

## 4. Architecture

```text
Architecture / planner completion
  │
  ├─ prose / markdown (optional; ignored for fan-out)
  └─ wire candidate(s):
       • Finding.summary / evidence / full_output JSON or fenced block
       • optional future PlanResult.wave_plan structured field
              │
              ▼
     extract → normalize (flat aliases only) → validate WavePlan
              │                         │
              │ nested / invalid        │ ok
              ▼                         ▼
         send_back (+ reason)    record_wave_plan
                                        │
                                        ▼
                         RailJobState slice catalog
                         (wave_slices + decompose_plan / rich slices
                          + optional depends_on)
                                        │
                                        ▼
                    is_wave_plan_ready → spawn_wave_makers (spawn-ready)
```

### 4.1 Ownership

| Layer | Owns | Must not |
|-------|------|----------|
| LLM + transfer | Flat WavePlan via wire fields, dumps, allowlist, or findings blob | Nested wave trees; treating dumps as SoT after apply |
| Autopilot gate | Extract, reject nesting, optional flat coerce, validate, send_back text | Accept architecture without slices when `require_plan` |
| LoopRail | `record_wave_plan` → slice catalog; streaming spawn (RFC-231 §9) | Persist nested wave objects; wave-stage spawn gates |
| Rail YAML | `fanout.require_plan` and planner briefs (flat examples + optional deps) | `fanout.artifact`; nested WavePlan examples in briefs |

## 5. Wire and canonical contracts

### 5.1 Canonical `WavePlan` (normative)

```json
{
  "wave_slices": ["auth", "desktop-shell", "api-demos", "tests"],
  "independence": "disjoint primary write-sets per slice",
  "rationale": "partition by ownership for parallel makers"
}
```

Rich flat form (equivalent SoT after apply):

```json
{
  "slices": [
    {"slice": "auth", "description": "identity + login", "priority": 80,
     "tags": ["implementation", "maker"]},
    {"slice": "desktop-shell", "description": "portable app shell"},
    {"slice": "showcase-chat", "description": "chat demo",
     "depends_on": ["auth"]}
  ],
  "independence": "disjoint write-sets where deps omitted",
  "rationale": "…"
}
```

`depends_on` (optional on each rich slice): list of **peer slice id strings**
that must reach terminal maker success before this slice is spawned. Unknown
ids → validate reject / send_back. Self-deps and cycles → reject.

String-only `wave_slices` form has no per-slice deps (all ready after
architecture). Prefer rich `slices[]` when edges are required.

Optional scalar fields: `scout_count`, `max_slices` (preferred), `max_waves`
(alias for expansion budget), `independence`, `rationale` (strings or null —
not objects).

Nested wrapper `{"wave_plan": { …flat… }}` remains allowed when the **inner**
object is flat (existing unwrap behavior).

### 5.2 Semi-structured completion (allowed)

Any of the following MAY supply the wire candidate (first successful flat
parse wins; prefer an explicit WavePlan finding over prose scrape):

1. Contribution `Finding.summary` that is (or embeds) flat WavePlan JSON.
2. `evidence_summary` / `full_output` containing a single fenced JSON block or
   one top-level flat object.
3. (Future) Dedicated structured field on the completion contribution /
   `PlanResult`, schema-constrained to flat `WavePlan`.

Markdown outside the JSON block is documentation only.

### 5.3 Flat coerce (optional, host)

Before `WavePlan.model_validate`, the host MAY apply **flat-only** normalizers:

| Input | Coerce to | Notes |
|-------|-----------|-------|
| `slices[].name` / `id` without `slice` | `slice` | Flat leaf alias |
| `rationale` / `independence` as non-string scalar | `str(...)` | Keep short; objects → **reject** |
| Empty strings in `wave_slices` | Drop | Existing strip behavior |

### 5.4 Nesting reject (normative — MUST)

Treat as **invalid wire** (no apply, architecture gate `send_back`):

| Pattern | Example |
|---------|---------|
| `wave_slices` is a dict (e.g. keyed by `WAVE-*`) | `{"WAVE-0": {"slices":[…]}}` |
| `wave_slices` items are objects that encode a wave | `[{"wave_id":"WAVE-0","slices":[…]}]` |
| Any `slices` / `wave_slices` entry contains nested `slices` / `children` / `waves` | Tree nodes |
| Top-level `waves: […]` schedule object used as the plan | Nested schedule SoT |
| `rationale` / `independence` as object/array | Non-scalar narrative |

**MUST NOT** flatten nested WAVE trees into `wave_slices` as a recovery path.
Operators who need emergency unstick set `wave_slices` on `rail_state.json`
explicitly (debug wiki); that is out-of-band recovery, not ingest.

Removed pre-Slice keys (`wave_modules`, `modules`, `module`) remain rejected
(IG-718).

### 5.5 Applied job state (SoT)

After accept:

- `RailJobState.wave_slices: list[str]` — flat leaf ids (compat / id list)
- `RailJobState.decompose_plan` — optional flat specs from rich `slices`,
  including `depends_on` when present
- `RailJobState.wave_plan_source_path` — optional path that supplied a file transfer
- `is_wave_plan_ready` iff non-empty catalog / `wave_slices` (or multi-form
  diagnose still yields flat)

`RailJobState` MUST NOT grow a nested `waves[]` tree field. Transfer forms
(dumps, structured path, findings blob) are not a second SoT after apply.
Runtime spawn maps (`spawned_slices`, `job_branch`, …) are defined in
RFC-231 §9.2 and MAY persist alongside the catalog.

## 6. Architecture gate and report-commit judgment

When `_is_architecture_planner_goal` and job `require_plan`, the Autopilot
**deterministic gate** (RFC-204 §1.3) runs as part of / before the report-commit
handler using CE + rail state (not a workspace re-probe):

1. Extract candidates from structured contribution fields, recommended dumps,
   allowlist paths, and fields already on the committed CE goal report /
   findings.
2. Reject nesting (§5.4) or fail validate → **`send_back`** with reason that
   includes the reject/validation detail (truncated).
3. Else `record_wave_plan` → **`accept`** (mirror recommended dumps).
4. Do **not** fall through to free-form LLM judgment that ignores the
   WavePlan structural result (fail-closed; RFC-231 / IG-714).

Send-back exhaustion and `retry_architecture` behavior remain RFC-204 /
LoopRail (per-subgoal budget). Trigger remains **`goal_report_committed`**
after the planner loop writes its CE report.

### 6.1 Planner briefs

Builtin `plan_milestones` (and rail `verbs:` overrides) MUST:

- Show a **flat** JSON example (`wave_slices` string list or flat `slices`
  with optional `depends_on`).
- Recommend dumps (`.soothe/wave-plan.json`, jobs dump) and structured
  `wave_plan_path` for custom paths; allow findings blob.
- State explicitly: **no nested waves/slices**; deps are peer slice ids, not
  wave rounds.
- Forbid teaching `WAVE-0` / schedule trees as the machine deliverable.

## 7. Error handling

| Failure | Behavior |
|---------|----------|
| Missing WavePlan when `require_plan` | `send_back` + missing-plan reason |
| Nested waves/slices detected | `send_back` + nesting reject reason (no apply) |
| Flat shape invalid after coerce | `send_back` + first pydantic error |
| Path escapes workspace/jobs | `send_back` + escape detail |
| Send-back budget exhausted | Subgoal `failed` → `retry_architecture` (rail) |

## 8. Testing strategy

| Layer | Coverage |
|-------|----------|
| Parse | Flat string list + rich `slices` accept |
| Nesting | Dict `wave_slices`, WAVE object list, nested `slices` → None / reject |
| Coerce | Flat aliases only; object `rationale` still rejects |
| Gate | Architecture accept applies `rail_state.wave_slices`; send_back text contains field error |
| Transfer | Jobs dump, `.soothe/wave-plan.json`, allowlist, structured path, findings blob |
| Fan-out | `spawn_wave_makers` uses flat ids; `depends_on` delays spawn only |
| Deps validate | Unknown / cycle / self-dep → reject + send_back |

## 9. Migration / rollout

1. Document contract (this RFC); amend RFC-231 §9.
2. Implementation IG: nesting detector + send_back detail; optional flat coerce;
   brief copy updates on greenfield/migration `plan_milestones`.
3. Update debug wiki WavePlan stall section: flat example; nesting is not
   recoverable via flatten.
4. No on-disk migration of old nested artifacts (already non-SoT).

## 10. Decision log

| Topic | Decision |
|-------|----------|
| Nested waves/slices on wire | **Forbidden** — reject, do not flatten |
| Semi-structured markdown + JSON | **Allowed** as wire; SoT remains flat job state |
| Filesystem WavePlan | Transfer OK (recommended dumps / allowlist / `wave_plan_path`); SoT remains flat job state (IG-722) |
| Gate vs LLM consensus | Deterministic gate when `require_plan` |
| Coerce scope | Flat aliases only; no keyword slice invention (RFC-630) |
| Job state shape | Flat catalog (`wave_slices` / `decompose_plan`) only — no nested waves |
| Per-slice `depends_on` | Optional peer slice ids; omitted ⇒ ready after architecture |
| Structured contribution fields | `wave_plan` / `wave_plan_path` on PlanResult + GoalDispatchContextContribution (IG-722) |
| Wave rounds in plan payload | Forbidden as nested objects; expansion budget is scalar only |

## 11. Open questions

- Max length / slice-count caps surfaced in send_back vs silent clamp only.
- Operator CLI (`soothe autopilot wave-plan set`) vs rail_state edit for recovery.

## 12. Suggested implementation routing

1. **IG-721** (implemented): `parse_wave_plan_payload` nesting guards + send_back
   reason plumbing in `_architecture_wave_plan_consensus_gate`; flat coerce;
   brief / wiki / skill updates.
2. **IG-722** (implemented): multi-form transfer + structured `wave_plan` /
   `wave_plan_path`; recommended dumps; SoT remains job rail state.
3. Optional follow-on: operator CLI `wave-plan set`.
4. **IG-732**: validate/persist per-slice `depends_on`; planner brief
   examples; spawn-ready mapping slice id → goal id; host worktrees.

## Appendix A: relation to prior docs

| Document | Relation |
|----------|----------|
| RFC-231 §9 | Amended: flat wire; optional slice `depends_on`; slice catalog SoT; streaming spawn (no wave barrier) |
| Streaming design draft | `docs/drafts/2026-08-08-streaming-slice-dag-worktree-lifecycle-design.md` |
| IG-720 | Historical findings-only file ban; SoT still rail_state; amended by IG-722 |
| IG-722 | Multi-form transfer (dumps, structured path, findings blob); SoT = job state |
| IG-718 | Slice terminology; nesting reject complements module-key hard cut |
| IG-704 / IG-714 | Host ingest + architecture gate; add nesting + error detail |
| RFC-630 | No keyword heuristics for inventing slices from prose |
| RFC-204 | Send-back / fail / `retry_architecture` unchanged |
