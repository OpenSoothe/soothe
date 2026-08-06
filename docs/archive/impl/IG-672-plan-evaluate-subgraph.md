# IG-672: Plan Evaluate Subgraph (Gap + Assess Unity)

**RFCs**: RFC-220 (Loop Graph), RFC-214 (ledger + planner assembly), RFC-604 (`StatusAssessment`), RFC-624 (CE goal audit), RFC-630 (intake routing)
**Amends**: IG-557 Phase E (sibling `plan_gap_analysis` → `plan_assess`), IG-663 (flat stem; introduces **one** nested plan subgraph), IG-653 / IG-671 (cost controls)
**Related**: IG-555 (iter=0 anti-anchoring), IG-589 (terminal assess consistency), IG-665 / IG-668 (gap/assess wire + stall soft-fail), IG-476 (fresh-loop skip)
**Status**: Implemented (P1 sequential evaluate station + P2 parallel inventory config)
**Created**: 2026-08-01

---

## Goal

Unify mid-goal **gap analysis** and **status assessment** into a single StrangeLoop plan station — **`evaluate`** — implemented as a LangGraph **subgraph**.

Conceptually, gap and assess are one evaluation goal: *measure progress against GOAL evidence and decide continue / replan / terminate.* Operationally, keep **split structured schemas** (rich inventory vs thin routing) so nested fields (`components[].evidence`, `gap`, etc.) stay complete. Optionally fan out inventory legs in parallel under a **config switch** (default sequential) to measure wall-clock and quality gain.

**Hard cut**: remove legacy opt-in/skip knobs and the sibling `analyze_gaps` → `assess` parent-graph path. Evaluation is **always on** for applicable mid-goal spines.

---

## Non-goals

- Merging `PlanGapAnalysis` and `StatusAssessment` into one mega structured-output schema
- Tool / CoreAgent execution inside evaluate (IG-557 lock unchanged)
- Changing `plan_generate`, execute, structural-keep, or fresh-loop semantics beyond routing into `evaluate`
- Nesting additional StrangeLoop subgraphs outside plan-evaluate
- Implementing code in this document revision (design + acceptance only)

---

## Motivation

### Conceptual unity, operational split

| Role | Schema | Decode job |
|------|--------|------------|
| Inventory | `PlanGapAnalysis` | Facets, per-component evidence/gaps, distance, remaining work |
| Decision | `StatusAssessment` | `continue` / `replan` / `done` + readiness / gap_alignment |

A single LLM call that emits both tends to **starve nested inventory fields** and **couple inventory to routing politics** (mark components satisfied to justify `done`). Sibling parent nodes (`analyze_gaps`, `assess`) express the split but:

1. Fragment the evaluation goal across two stem stations
2. Rely on opt-out flags that operators treat as “always true”
3. Make parallel inventory experimentation awkward (must bolt onto one node or fork the stem)

### Legacy config to remove

| Flag (remove) | Today | Why remove |
|---------------|-------|------------|
| `plan_gap_analysis_enabled` | default `true` | Evaluate is the mid-goal path; no process-wide disable |
| `plan_gap_skip_simple_mid_loop` | default `true` | Mid-loop simple still needs the same evaluate contract; cost control moves to structural-keep / skip-generate / gap **mode**, not “skip inventory” |

Applicable-path **skips** remain structural (no evidence yet, fresh-loop, structural keep) — not YAML toggles that disable evaluation.

### Performance / stability pressure (unchanged facts)

- IG-653: gap+assess wall-clock often dominates mid-loop; both already on `fast`
- IG-671: structural keep and assess `skip_generate` cut redundant plan-phase work
- IG-665: gap soft-fails (90s wall / coerce) so assess can continue without a map
- Premature `done` is gated by `assess_respects_gap_analysis` + terminal readiness (IG-557 / IG-589)

---

## Design summary

```text
Parent stem (plan):
  gather_evidence
    ├─ keep_plan / fresh skip → (unchanged shortcuts)
    └─ evaluate ──────────────────────────────┐
         (LangGraph subgraph)                 │
         seed → inventory → reduce → assess   │
         out: StatusAssessment + routes       │
         stash: PlanGapAnalysis (scratch/CE)  │
                                              ▼
         → skip_generate | continue_generate | goal_done
```

**Parent I/O contract**

| Direction | Payload |
|-----------|---------|
| In | Projected ledger messages (gap/assess projection), GOAL, PRIOR PROGRESS, PLAN COVERAGE, optional CE bundle — assembled **once** at subgraph entry |
| Out | Same routing keys as today’s `node_plan_assess` (`assess_route`, `plan_route`) + scratch `plan_assessment` / optional `plan_result` |
| Side | Scratch + CE `last_gap_analysis` / `last_assessment` when inventory / assess succeed |

Internal inventory parallelism is an implementation detail of `evaluate`; parent routing does not see `analyze_gaps`.

---

## Graph topology

### Parent stem change (amends IG-663)

| Legacy stem | This IG |
|-------------|---------|
| `analyze_gaps` → `assess` | Single station `evaluate` (subgraph) |
| `gather_evidence` → `analyze_gaps` \| `assess` | `gather_evidence` → `evaluate` (when evaluation needed) |
| Clarification origins `analyze_gaps` / `plan_gap_analysis` / `assess` / `plan_assess` | Normalize to `evaluate` (dual-read legacy for resume) |

IG-663 non-goal “no LangGraph subgraph nesting” is **amended for this station only**. Stem readability stays: one plan station named `evaluate`, not two sibling inventory/decision nodes.

### Proposed parent edges

```text
gather_evidence
  ├─ evidence_gather_route=keep_plan              → commit_plan
  ├─ evidence_gather_route=plan_generate_skip_evaluate → generate_plan   # IG-476
  └─ evidence_gather_route=evaluate              → evaluate
                                                    ├─ assess_route=skip_generate      → commit_plan
                                                    ├─ assess_route=continue_generate → generate_plan
                                                    └─ plan_route=goal_done            → finalize
```

Remove `evidence_gather_route=analyze_gaps` and `evidence_gather_route=assess` as mid-goal dual paths. Continuation discriminator (iter=0 continue-loop) runs as an **internal branch** of `evaluate` (same behavior as today’s `_handle_continuation_first_plan`), not a separate parent `assess` node on the complex spine.

**Exception — preprocess shortcuts unchanged**

- Fresh simple → `generate_plan` (skips gather + evaluate)
- Fresh trivial → `commit_plan`
- Continuation + trivial/simple at preprocess may still enter `evaluate` for continuation routing (replacing direct `assess` edge), **or** keep a thin parent edge into `evaluate` with `evaluate_mode=continuation` — implementer’s choice, behavior must match RFC-226.

### Evaluate subgraph (internal)

```text
evaluate_entry
  ├─ continuation_fast_path? → emit routes / bootstrap (no inventory)
  ├─ no_execute_evidence?    → assess_only (inventory skipped; structural)
  └─ inventory_enabled
        ├─ seed_facets (deterministic; optional tiny decompose later — non-default)
        ├─ gap_mode=sequential → one PlanGapAnalysis call
        └─ gap_mode=parallel AND facets >= min_facets
              → fan-out GoalComponentStatus legs (≤ max_concurrency)
              → reduce → PlanGapAnalysis
  → assess (StatusAssessment; feed-forward gap)
  → normalize + terminal gates (existing plan_step_safety)
  → evaluate_exit (routes)
```

---

## Schemas (unchanged contracts)

Keep schemas split. Do **not** add routing fields to gap or inventory fields to assess.

### `PlanGapAnalysis` / `GoalComponentStatus` (inventory)

Existing fields remain authoritative:

- `components[]`: `component`, `status`, `evidence`, `gap`
- `evidence_summary`, `remaining_gaps`, `distance_from_goal`, `gap_reasoning`

Parallel legs emit **`GoalComponentStatus`-shaped** (or equivalent micro-schema) results; reducer builds full `PlanGapAnalysis`.

### `StatusAssessment` (decision)

Existing fields remain authoritative:

- `status`, `goal_progress`, `assessment_reasoning`
- `require_goal_completion`, `terminal_readiness`, `gap_alignment`

Deterministic post-process unchanged in spirit:

- `normalize_status_assessment`
- `derive_goal_progress_from_status`
- `assess_respects_gap_analysis`
- `terminal_assess_may_complete`
- IG-555 / stuck / simple-intake force-done rules

---

## Config

### Remove (hard cut — no deprecation shim)

```yaml
# DELETE from agent.loop / LoopConfig / templates / packaged soothe.yml
plan_gap_analysis_enabled: true
plan_gap_skip_simple_mid_loop: true
```

Reject unknown keys via existing config strictness if present; do not map them silently.

### Add (`agent.loop`)

```yaml
agent:
  loop:
    # Inventory strategy inside evaluate (assess always runs after inventory or assess-only skip)
    plan_evaluate_gap_mode: sequential   # sequential | parallel
    plan_evaluate_gap_max_concurrency: 4
    plan_evaluate_gap_min_facets: 2
    plan_evaluate_gap_wall_clock_seconds: 90   # whole inventory phase soft budget
    plan_evaluate_gap_leg_timeout_seconds: 45  # per parallel leg; sequential uses wall budget

    plan_evaluate_assess_model_role: fast
    plan_evaluate_gap_model_role: fast
    plan_evaluate_prompt: { ... }  # was plan_assess_prompt
    plan_structural_keep_enabled: true
    plan_structural_keep_max_streak: 3
```

| Field | Default | Semantics |
|-------|---------|-----------|
| `plan_evaluate_gap_mode` | `sequential` | Control arm = today’s single gap call; `parallel` = facet fan-out for A/B |
| `plan_evaluate_gap_max_concurrency` | `4` | Cap parallel legs |
| `plan_evaluate_gap_min_facets` | `2` | If seeded facets &lt; N, force sequential even when mode=parallel |
| `plan_evaluate_gap_wall_clock_seconds` | `90` | Soft-fail inventory → assess without map (migrate from `_GAP_WALL_CLOCK_SECONDS`) |
| `plan_evaluate_gap_leg_timeout_seconds` | `45` | Soft-fail one leg; reduce with partial components |

**Enabled by default**: when gather routes to evaluate and execute evidence exists, inventory **runs** (sequential unless parallel configured). No YAML flag to disable evaluate or skip inventory for simple mid-loop.

### Structural skips (code, not removed flags)

| Condition | Behavior |
|-----------|----------|
| IG-476 fresh-loop | Skip evaluate → `generate_plan` |
| IG-671 structural keep | Skip evaluate → `commit_plan` |
| iter=0 / new_goal, no step_results, no execute ledger | Evaluate → **assess_only** (no inventory) — same as today’s gap skip reason |
| Continuation bootstrap / forced generate | Internal evaluate branches; may skip inventory |

---

## Inventory modes

### Sequential (default)

One structured call → `PlanGapAnalysis` via existing `analyze_plan_gap` / `call_kind=gap` assembly + `coerce_plan_gap_analysis_wire_dict`. Soft-fail → `plan_gap=None` → assess.

### Parallel (opt-in experiment)

1. **Seed facets** (deterministic first): from `intent.goal_description` / GOAL segmentation / prior CE `last_gap_analysis` component names. Prefer 1 facet when single CoreAgent deliverable (align with current gap instructions).
2. If `len(seeds) < plan_evaluate_gap_min_facets` → sequential fallback.
3. Else fan-out ≤ `max_concurrency` micro-calls (shared ledger prefix; facet-specific instruction).
4. **Reduce** in code:
   - Merge components by seed order
   - Missing / timed-out legs → `status=partial` or `not_started`, **never** invent `satisfied`
   - `distance_from_goal=at_goal` **only if** every seeded facet `satisfied` and no open gaps
   - Build `evidence_summary` / `remaining_gaps` / `gap_reasoning` from legs (concat + clip) or one tiny reduce call later (non-default; out of v1)
5. Feed reduced `PlanGapAnalysis` into assess exactly as today.

### Failure policy

| Layer | Policy |
|-------|--------|
| Inventory (any mode) | Soft — assess continues; missing map disables gap-terminal proof |
| Parallel leg | Soft — partial map; cannot claim `at_goal` if any seed missing |
| Assess | Existing fallbacks (IG-668); drives routing |
| Tools | Forbidden |

---

## Module / file plan (for a future impl pass)

| Area | Change |
|------|--------|
| `sloop/orchestrator/stations.py` | Add `EVALUATE = "evaluate"`; map legacy `analyze_gaps` / `plan_gap_analysis` / mid-goal assess origins → `evaluate`; ledger phase writers: decide wire-stable string (prefer keep `plan_assess` / `plan_gap_analysis` for CE/client filters **or** introduce `plan_evaluate` with dual-read — must not break soothe-sdk card_binder) |
| `sloop/orchestrator/builder.py` | Replace `ANALYZE_GAPS` + mid-goal `ASSESS` edges with `EVALUATE` subgraph compile |
| `sloop/orchestrator/routing.py` | `route_after_evidence_gather` → `evaluate`; remove `analyze_gaps` branch |
| `sloop/stages/plan/evaluate/` (new) | Subgraph builder, entry/exit, inventory sequential/parallel, reduce |
| `sloop/stages/plan/analyze_gaps.py` | **Delete** after logic moves into evaluate inventory |
| `sloop/stages/plan/assess.py` | Split: continuation + routing helpers reused; parent `node_plan_assess` removed from stem or becomes evaluate exit wrapper |
| `sloop/stages/plan/gather_evidence.py` | Drop `_gap_analysis_enabled` / `_should_run_gap_analysis` flag reads; route `evaluate` when not keep/fresh; structural assess-only when no evidence |
| `sloop/cognition/planner.py` | Keep `analyze_plan_gap` / `assess_status`; add optional per-facet invoke + timing tags |
| `sloop/config/models.py` + `config/soothe.template.yml` + packaged template | Remove two flags; add evaluate gap knobs; sync develop/packaged copies |
| Clarification origins | Resume dual-read legacy → `evaluate` |
| Docs | Update `docs/diagrams/strange_loop_graph_nodes.md`, stem mmd, wiki plan-phase notes |
| Tests | Retarget gap/assess stage tests to evaluate; config defaults; parallel fallback; soft-fail |

Exact package layout may use `stages/plan/evaluate.py` + `evaluate_subgraph.py` if a directory is overkill — keep one owner module for the subgraph.

---

## Observability

Extend IG-653 timing lines:

```text
[Plan] phase=evaluate-gap mode=sequential|parallel facets=N ok_legs=K/N
       elapsed_ms=... prompt_chars=... iter=...
[Plan] phase=evaluate-assess elapsed_ms=... prompt_chars=... iter=...
[Plan] phase=evaluate elapsed_ms=... route=skip_generate|continue_generate|goal_done iter=...
```

TUI `plan_phase_status`:

- Inventory: `"Analyzing coverage"` (reuse)
- Assess: `"Assessing progress"` (reuse)
- Optional parent: `"Evaluating progress"` once at evaluate entry

Langfuse: parent run `evaluate`; children `evaluate-gap` / `evaluate-gap-leg-{i}` /
`evaluate-assess` (pinned to goal-loop `trace_id`; IG-663 suffix style).

### A/B measurement (parallel gain)

Hold constant: `plan_evaluate_gap_model_role`, structural-keep, ledger caps. Toggle only `plan_evaluate_gap_mode`.

| Metric | Parallel “win” |
|--------|----------------|
| `phase=evaluate-gap elapsed_ms` | ↓ |
| Token / cost sum | may ↑ — report separately |
| Non-empty `components[].evidence` / `gap` rate | ↑ |
| Inventory soft-fail / assess-without-map rate | ≤ sequential |
| Premature `done` after gates | not worse |
| End-to-end plan-phase ms when gap was bottleneck | ↓ |

---

## Cleanse (required when implementing)

- Delete `plan_gap_analysis_enabled`, `plan_gap_skip_simple_mid_loop` from config models, templates, develop overlays, packaged daemon templates, tests, docs
- Delete parent station usage of `ANALYZE_GAPS` / `node_plan_gap_analysis` as sibling of assess
- Remove gather_evidence branches that emit `analyze_gaps` / bare mid-goal `assess` routes
- Rename fresh-loop route `plan_generate_skip_assess` → `plan_generate_skip_evaluate`
- Align timing / Langfuse phase strings to `evaluate-gap` / `evaluate-assess` (drop in-code `assess` / `analyze-gaps` aliases)
- Keep clarification / ledger dual-read for persisted `assess` / `analyze_gaps` / `plan_assess` / `plan_gap_analysis` origins
- Update IG-671 text references that describe “skip gap for simple mid-loop” as a config flag
- Do **not** leave dead dual path “if legacy flag …”

---

## Phased implementation (future; not this revision)

| Phase | Scope | Exit criteria |
|-------|-------|---------------|
| **P0** | IG approved; config surface locked | This document reviewed |
| **P1** | Parent `evaluate` station = sequential inventory + assess (behavioral parity with today’s gap→assess when gap would have run; simple mid-loop now includes inventory) | Parity tests green; two flags gone |
| **P2** | Parallel inventory behind `plan_evaluate_gap_mode=parallel` | Soft-fail + reduce rules; A/B logs |
| **P3** | Docs/diagrams; diagnose skill greps; optional wiki | Stem shows `evaluate` |

P1 must not wait on parallel. Default remains `sequential`.

---

## Acceptance criteria

1. Mid-goal complex spine has **no** parent edge `analyze_gaps` → `assess`; only `evaluate`.
2. Config no longer defines `plan_gap_analysis_enabled` or `plan_gap_skip_simple_mid_loop`.
3. With execute evidence present, evaluate runs inventory by default (sequential).
4. Simple mid-loop no longer skips inventory via config; structural-keep / fresh-loop still skip whole evaluate when applicable.
5. iter=0 / no execution → assess-only inside evaluate (no inventory LLM).
6. `PlanGapAnalysis` and `StatusAssessment` remain separate schemas; assess still receives gap feed-forward.
7. Terminal gates still reject `done` when gap shows open components / distance ≠ `at_goal`.
8. Inventory soft-fail never aborts the graph; assess still routes.
9. `plan_evaluate_gap_mode=parallel` is off by default; when on, respects concurrency + min_facets + budgets.
10. Parallel reduce never emits `at_goal` if any seeded facet leg failed or is open.
11. Clarification resume accepts legacy origins and maps to `evaluate`.
12. Wire/ledger phase compatibility with soothe-sdk filters preserved (dual-read if renamed).
13. `./scripts/verify_finally.sh` green when implemented.
14. No tools / CoreAgent inside evaluate.

---

## Risks and locks

| Risk | Lock |
|------|------|
| Nested subgraph hurts stem clarity | One nested graph only; parent name `evaluate`; diagrams updated |
| Simple mid-loop latency ↑ (inventory no longer skipped) | Mitigate via structural keep + skip_generate; measure before considering facet=0 skip (must be structural, not resurrected YAML flag) |
| Parallel cost explosion | Default sequential; min_facets + max_concurrency |
| Premature `at_goal` from partial merge | Reducer rules above |
| Continuation / assess routing regressions | Port `_handle_continuation_first_plan` behavior verbatim into evaluate entry |
| Client ledger phase rename break | Prefer dual-read; do not rename writers without sdk bump |

---

## RFC / IG alignment

| Doc | Relationship |
|-----|--------------|
| RFC-220 | Amends plan spine: optional gap node → required `evaluate` subgraph station on mid-goal path |
| RFC-214 | Unchanged projection kinds (`gap` / `assess`); assembly still assess-only ledger for both |
| RFC-604 | `StatusAssessment` unchanged |
| RFC-624 | `last_gap_analysis` / `last_assessment` still CE audit; no ledger pairs for inventory/assess |
| IG-557 Phase E | Supersedes sibling-node topology; keeps schemas, soft-fail, feed-forward, no-tools |
| IG-663 | Amends “no nested subgraphs” for `evaluate` only; stem gains `evaluate`, drops sibling `analyze_gaps` |
| IG-653 / IG-671 | Timing + keep/skip-generate retained; remove simple mid-loop gap-skip flag |

---

## Open questions (resolve before P1 code)

1. **Parent station id**: `evaluate` vs reuse `assess` as subgraph wrapper — recommendation: **`evaluate`** for conceptual clarity.
2. **Ledger phase string**: keep writing `plan_gap_analysis` / `plan_assess` for sdk filters vs new `plan_evaluate` with dual-read.
3. **Preprocess continuation edge**: route continuation+trivial/simple into `evaluate` vs keep a thin legacy `assess` alias node that only delegates into the same subgraph compile.
4. **Facet seeding v1**: deterministic only vs optional LLM decompose (default deterministic).

---

## Validation (when implementing)

- Unit: gather routes to `evaluate`; flags absent from config model; sequential default; parallel fallback when facets &lt; min; wall/leg soft-fail; reduce `at_goal` invariants; continuation bootstrap parity; terminal gap guard parity
- Integration: multi-part mid-goal does not early-complete; simple mid-loop still completes when evidence supports done
- Manual A/B: toggle `plan_evaluate_gap_mode` on a multi-facet goal; compare `[Plan] phase=evaluate-gap` lines

---

## Document status

P1 + P2 landed: parent stem station ``evaluate`` (inventory → assess), legacy
``plan_gap_analysis_enabled`` / ``plan_gap_skip_simple_mid_loop`` removed,
``plan_evaluate_gap_mode`` defaults to ``sequential`` with optional ``parallel``.
