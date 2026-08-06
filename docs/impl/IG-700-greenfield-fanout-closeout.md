# IG-700: Greenfield fan-out closeout — boundaries, job-scoped plan, hidden artifact

**Created**: 2026-08-06  
**Status**: Implemented  
**Supersedes / extends**: [IG-699](IG-699-llm-determined-rail-fanout-width.md)  
**Related**: [IG-687](IG-687-greenfield-system-rail.md),
[IG-678](IG-678-autopilot-ce-rails-production-readiness.md),
[IG-695](IG-695-rail-wave-idle-feedback-deadlock.md),
RFC-222, RFC-630

---

## Goal

Ship the **final** greenfield fan-out design so that:

1. **Concept boundaries** stay clean (engine ≠ LoopRail ≠ LLM policy).
2. Fan-out **width and modules are LLM-authored** (no rigid default module list).
3. Wave planning is **job-scoped** (no multi-job clash on one workspace).
4. Artifact **paths are hidden** from user-facing surfaces (CLI / TUI / goal copy).
5. Non-greenfield rails are **not polluted** with wave/fanout state at bind.

IG-699 delivered the first cut (structured plan, `require_plan`, remove submit
knobs). This IG closes the remaining gaps.

---

## Concept model (MUST)

```text
┌──────────────────────────────────────────────────────────────┐
│ Autopilot engine (general)                                   │
│ goals, deps, WorkerPool, max_parallel_goals, reservation,    │
│ consensus, scheduling, submit(description, rail_id, …)       │
├──────────────────────────────────────────────────────────────┤
│ LoopRail (per-rail choreography)                             │
│ YAML flow / conditions / fanout *contract*, builtins, when   │
│ Wave / wave_index / max_waves = greenfield-system ONLY       │
├──────────────────────────────────────────────────────────────┤
│ LLM + job artifact (policy)                                  │
│ module names, count, rationale for this job’s next wave      │
└──────────────────────────────────────────────────────────────┘
```

| Concept | Owner | Must not |
|---------|--------|----------|
| Pool / schedule cap | Engine | Module names, waves |
| When to spawn / integrate / review | Rail YAML `flow` | Submit kwargs |
| Wave / `max_waves` | `greenfield-system` rail | Treated as global Autopilot |
| Module list & width | LLM via job-scoped plan | Fixed `core/api/cli/tests` |
| Artifact filesystem path | Rail runtime (internal) | CLI, TUI, user goal text |

**Wave is not an Autopilot engine concept** — it is greenfield LoopRail
choreography. Engine only runs the goals the rail creates.

---

## Problems this IG closes

| # | Issue | Impact |
|---|--------|--------|
| P1 | Project path `.soothe/wave-plan.json` | Two jobs on one workspace overwrite each other |
| P2 | Path in architecture goal description | Leaks into TUI / “show goal” user surface |
| P3 | Bind stamps `require_plan` / artifact / `max_waves` on **all** rails | Greenfield concepts pollute `feature-dev` / spike state |
| P4 | IG-699 / code still mention `default_modules` in places | Conflicts with LLM-only policy |
| P5 | Operator mental model “autopilot wave” | Misattributes rail concept to engine |

---

## Design

### A. Job-scoped artifact store

**Source of truth** (aligned with `rail_state.json`):

```text
$SOOTHE_DATA_DIR/jobs/{job_id}/wave-plan.json
```

(Typically `~/.soothe/data/jobs/{job_id}/wave-plan.json`.)

Rail YAML template (internal config only):

```yaml
# greenfield-system.yml
fanout:
  artifact: "{job_id}/wave-plan.json"   # relative to jobs_root
  require_plan: true
  max_waves: 3
  # NO default_modules
```

Expand `{job_id}` at bind / plan / ingest. Never use a workspace-root singleton.

Optional **non-authoritative** workspace mirror for humans (out of scope unless
needed): `{workspace}/.soothe/jobs/{job_id}/wave-plan.json` — must not be the
load path for spawn.

### B. Hide path from user surface

| Surface | Behavior |
|---------|----------|
| CLI / TUI / submit | No artifact path |
| Architecture goal **user-visible** description | Opaque: “define independent ownership units for wave 1”; **no** `jobs/…` path |
| Agent write API | Prefer **`record_wave_plan(...)`** (or structured completion fields) — agent fills modules, runtime persists |
| Rail YAML / debug / inspect skill | Path OK (operator forensics) |

Preferred agent contract:

```text
User/TUI:  Architecture: define wave-1 ownership units
Agent:     record_wave_plan(modules=[...], rationale=...)  OR structured fields
Rail:      persist → jobs/{job_id}/wave-plan.json
Spawn:     load from jobs_root (internal)
```

Do **not** instruct the agent to `write_file` a user-visible path in the goal
card text.

### C. Bind hygiene (fanout opt-in)

On `LoopRailInterpreter.bind_job`:

- If rail YAML has **no** `fanout:` block → do **not** set `require_plan`,
  wave artifact, `max_waves`, or call `ingest_wave_plan`.
- `require_plan` only when declared (greenfield: `true`).
- `feature-dev` / `spike` remain scout-based; no ghost wave-plan expectations.

Engine still injects only `engine_max_parallel_goals` (= `max_parallel_goals`).

### D. Greenfield runtime flow

```text
job_start → plan_milestones
  architecture produces structured wave plan (tool / fields)
  runtime persists job-scoped wave-plan.json
architecture_ready (requires wave_plan_ready when require_plan)
  → spawn_wave_makers
      ingest → N makers; clamp ≤ engine_max_parallel_goals
      missing plan → skip (fail closed; no rigid defaults)
→ integrate → commit → review → QA → feedback…
ready_for_next_wave → spawn_wave_makers (refreshed plan)
  until max_waves or acceptance
dag_idle + architecture_ready → recovery when plan appears late
```

### E. Engine API (unchanged constraint)

`submit_task` / daemon submit must **not** grow:

- `wave_modules`, `scout_count`, `decompose_plan`, artifact paths

---

## Deliverables

- [x] Job-scoped wave-plan path under `jobs_root / {job_id}/`; template `{job_id}`
- [x] Remove / stop loading workspace `.soothe/wave-plan.json` as source of truth
- [x] `record_wave_plan` (or structured ingest) so agents never need the path
- [x] Architecture goal text: opaque user-facing copy (no filesystem path)
- [x] Bind: fanout / wave fields **only** when rail declares `fanout:`
- [x] Greenfield YAML: job-scoped artifact template; no `default_modules`
- [x] Clean dead `DEFAULT_WAVE_MODULES` / stale docs referencing project singleton
- [x] Update [IG-699](IG-699-llm-determined-rail-fanout-width.md) status → superseded by this IG for remaining work
- [x] Unit tests (see below)
- [x] Inspect skill / debug wiki pointer: look under `jobs/{id}/wave-plan.json`

---

## Tests

| Case | Expect |
|------|--------|
| Two jobs, same workspace, different plans | Independent files under each `jobs/{id}/`; spawn uses correct plan |
| Missing plan + `require_plan` | `architecture_ready` false / spawn skipped; zero makers |
| Valid 6-module plan + budget ≥ 6 | Six makers; arch-only deps |
| Plan with 10 modules, budget 3 | Three makers; `clamped_from=10` |
| Bind `feature-dev` | No `require_plan` / wave artifact / ingest |
| User-visible architecture description | No `jobs/` or `.soothe/wave-plan` substring |
| Submit API | Still no module/fanout kwargs |

---

## Acceptance criteria

1. Multi-job same project: no shared wave-plan file race.
2. Fan-out modules come only from LLM/job plan (clamped by pool), never a fixed 4-tuple.
3. Operators using CLI/TUI never need to know the artifact path for normal use.
4. Non-greenfield rails do not carry greenfield fanout state after bind.
5. Engine/rail/LLM ownership matches the concept table above.
6. `./scripts/verify_finally.sh` green for touched packages.

---

## Non-goals

- Parallelize integrate / commit / review / QA / feedback.
- Markdown/keyword scrape for modules (RFC-630).
- Making “wave” an engine-level Autopilot primitive.
- Changing workspace-reservation defaults.
- Full auto-merge of maker worktrees in integrate.

---

## Implementation order

1. Path resolver + migrate load/persist to `jobs/{job_id}/wave-plan.json`
2. Bind opt-in for `fanout:`
3. Hide path: opaque goal text + `record_wave_plan` / structured ingest
4. Tests + IG-699 pointer + inspect-skill note
5. Cleanse dead defaults / project-singleton references

---

## Ops / forensics (internal only)

```bash
# Job-scoped plan (after this IG)
cat ~/.soothe/data/jobs/$JOB/wave-plan.json
cat ~/.soothe/data/jobs/$JOB/rail_state.json   # wave_index, wave_modules, …
soothe autopilot job $JOB
```

Do not document the path as a user workflow in CLI help.

---

## References

- `packages/soothe/src/soothe/rails/builtin_rails/greenfield-system.yml`
- `packages/soothe/src/soothe/autopilot/rail/wave_plan.py`
- `packages/soothe/src/soothe/autopilot/rail/builtins_exec.py`
- `packages/soothe/src/soothe/autopilot/rail/interpreter.py` (`bind_job`)
- `packages/soothe/src/soothe/autopilot/service.py` (`_bind_rail_for_job`)
- `.agents/skills/inspect-autopilot-job/`
