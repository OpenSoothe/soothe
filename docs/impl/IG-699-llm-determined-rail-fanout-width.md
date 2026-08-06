# IG-699: LLM-determined LoopRail fan-out width

**Created**: 2026-08-06  
**Status**: Superseded for remaining gaps by [IG-700](IG-700-greenfield-fanout-closeout.md)
(first cut shipped: structured plan, `require_plan`, remove submit knobs)  
**Related**: [IG-700](IG-700-greenfield-fanout-closeout.md) (closeout plan),
[IG-687](IG-687-greenfield-system-rail.md),
[IG-678](IG-678-autopilot-ce-rails-production-readiness.md),
[IG-695](IG-695-rail-wave-idle-feedback-deadlock.md),
RFC-222 (Autopilot / WorkerPool), RFC-630 (no content-judgment heuristics)

---

## Goal

Let the **planner / architecture LLM** choose ready-DAG fan-out width
(module count and names) for rail jobs, instead of always falling back to a
hard-coded maker list. Fan-out policy lives in **LoopRail**; Autopilot engine
only supplies **capacity**.

---

## Architecture boundary (MUST)

Do **not** mix engine and rail. Autopilot is two layers:

| Layer | Owns | Must not own |
|-------|------|----------------|
| **Engine (general)** | WorkerPool, `max_loops` / `max_parallel_goals`, workspace reservation, scheduling, `submit_task(description, rail_id, workspace, …)`, CE goal DAG mutations via generic APIs | `wave_modules`, `scout_count`, `decompose_plan`, greenfield defaults, wave-plan schema, when to fan out |
| **LoopRail (declaration + builtins)** | YAML `flow` / `conditions` / optional `fanout:`, builtins (`plan_milestones`, `spawn_wave_makers`, …), `RailJobState`, job-scoped wave-plan contract under `jobs_root` | Pool sizing, submit wire fields for module lists |

```text
Operator submit  →  AutopilotService (engine)
                       │  binds rail_id + workspace
                       │  injects only engine_max_parallel_goals (= max_parallel_goals)
                       ▼
                 LoopRailInterpreter.bind_job
                       │  loads rail YAML fanout: {artifact, require_plan, …}
                       ▼
                 plan_milestones → architecture record_wave_plan / findings
                       ▼
                 architecture_ready → spawn_wave_makers
                       │  ingest job-scoped plan → resolve modules (rail policy)
                       │  clamp len(modules) ≤ engine_max_parallel_goals
                       ▼
                 CE create_goal × N (makers)
```

**Wrong (rejected in this IG):** putting `wave_modules` / `scout_count` on
`AutopilotSubmitParams` or `submit_task` — that leaks rail policy into the
engine API.

**Right:** architecture LLM writes the rail artifact; engine only caps
concurrency. Rail YAML declares the artifact path + `require_plan`, not a
fixed module list.

---

## Problem

Observed on greenfield job `921c6d32`:

1. Architecture goal produces a rich milestone map in prose.
2. `spawn_wave_makers` ignored that intent and used a code default of 4 modules.
3. Pool knobs (`max_parallel_goals=16`) cannot create ready width the rail never
   spawned.
4. Early mistaken design also mixed fan-out knobs onto submit — corrected here.

---

## Non-goals

- Parsing freeform milestone markdown (RFC-630).
- Parallelizing integrate / commit / review / QA / feedback.
- Changing workspace-reservation defaults.
- Teaching AutopilotService about greenfield module names.

---

## Design

### LoopRail declaration (contract only — not module names)

```yaml
# greenfield-system.yml (see IG-700 for job-scoped closeout)
fanout:
  artifact: "{job_id}/wave-plan.json"
  require_plan: true
  max_waves: 3
```

- **`artifact`**: jobs_root-relative template (typically under
  `$SOOTHE_DATA_DIR/jobs/{job_id}/`). Prefer `record_wave_plan` over agents
  writing paths (IG-700).
- **`require_plan`**: when true, `architecture_ready` waits for a valid plan and
  `spawn_wave_makers` refuses to invent modules.
- **No `default_modules`** — fan-out policy is LLM-authored; catalog rejects
  the key.
- Flow declares *when* (`architecture_ready` → `spawn_wave_makers`, including
  `dag_idle` recovery after the plan appears).

### LLM artifact = fan-out policy

```json
{
  "wave_modules": ["frontend", "ir", "passes", "backend-x86", "driver", "tests"],
  "independence": "disjoint write-sets per module",
  "rationale": "why this partition for this job"
}
```

The architecture goal chooses **names, count, and rationale**. Rail + engine
only validate schema and clamp to `max_parallel_goals`.

### Precedence

1. LLM artifact → `wave_modules` / `decompose_plan`
2. Else **missing_plan** (skip spawn / block `architecture_ready`) — never a
   fixed core/api/cli/tests list

### Engine contribution

Bind injects `engine_max_parallel_goals` from `autopilot.max_parallel_goals` only.

---

## Deliverables

- [x] Clear Engine vs LoopRail boundary (this section)
- [x] `WavePlan` schema + load/clamp helpers under `autopilot/rail/`
- [x] Rail YAML `fanout:` on `greenfield-system` + catalog parse
- [x] `plan_milestones` contract (opaque; path hidden — IG-700)
- [x] `spawn_wave_makers` ingest + resolve + engine budget clamp
- [x] Autopilot submit / daemon **without** rail fan-out knobs
- [x] Unit tests (width N, clamp, rail default, catalog fanout)
- [x] Remaining gaps closed in [IG-700](IG-700-greenfield-fanout-closeout.md)

---

## Acceptance criteria

2. Valid artifact with 6 modules + `max_parallel_goals ≥ 6` → 6 makers.
3. Missing artifact → `architecture_ready` false / spawn skipped (no rigid
   default modules).
4. No markdown scrape; no `wave_modules` on submit/engine wire.
5. Gate phases remain serial; rail unit tests green.

---

## Ops

```bash
# Job-scoped plan (IG-700) — operator forensics only
cat ~/.soothe/data/jobs/$JOB/wave-plan.json
# Rail state mirrors modules after spawn
cat ~/.soothe/data/jobs/$JOB/rail_state.json | jq .wave_modules
```

---

## References

- `packages/soothe/src/soothe/rails/builtin_rails/greenfield-system.yml` (`fanout:`)
- `packages/soothe/src/soothe/rails/catalog.py` (`RailDefinition.fanout`)
- `packages/soothe/src/soothe/autopilot/rail/wave_plan.py`
- `packages/soothe/src/soothe/autopilot/rail/builtins_exec.py` (`spawn_wave_makers`)
- `packages/soothe/src/soothe/autopilot/service.py` (bind injects budget only)
