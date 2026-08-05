# IG-686: Autopilot Job Artifacts + `top` Polish

**Created**: 2026-08-05  
**Status**: Implemented  
**Related**: [RFC-228 §autopilot_top](../specs/RFC-228-autopilot-job-ipc.md),
[IG-679](IG-679-autopilot-top-command.md),
[IG-677](IG-677-autopilot-job-loop-index.md),
[IG-RQJ-02](IG-RQJ-02-rail-trace-continuity-analysis.md)

---

## Executive Summary

Polish autopilot so **job** and **loop** are distinct on disk and in the live
dashboard:

1. Job-scoped artifacts (`rail_trace.jsonl`) live under `data/jobs/{job_id}/`,
   not under `data/loops/`.
2. `soothe autopilot top` uses the alternate screen (linux-`top` full terminal),
   shows execution elapsed as `HH:MM:SS`, and nests each goal’s planned
   **StepDAG** under the goal DAG.

---

## Problem

| Issue | Today |
|-------|--------|
| Job artifacts under loops | `JsonlRailTraceStore` root is `SOOTHE_DATA_DIR/loops` → `loops/{job_id}/rail_trace.jsonl`, conflating job soft-state with StrangeLoop assignment dirs (`loops/autopilot__{job}__{uuid}/`) |
| Thin `top` body | Only `steps N/M` from `GoalReport`; no planned `GoalNode.steps` / per-step status |
| No execution clock | Header wall clock only; no job/loop elapsed |
| Partial screen | Rich `Live(screen=False)` redraws inline instead of taking the full terminal |

Concept hierarchy (RFC-228 / IG-677):

```text
Job (root GoalNode.id)
  └── Goal DAG
        ├── StepDAG per goal (planned.steps)
        └── JobLoopIndex → data/loops/autopilot__{job}__{uuid}/
```

---

## Design

### 1. Disk layout

```text
~/.soothe/data/jobs/{job_id}/
  rail_trace.jsonl          # job-scoped rail soft-state

~/.soothe/data/loops/autopilot__{job_id}__{uuid}/
  runner.log, checkpoints…  # StrangeLoop assignment only
```

- Trace remains keyed by **`job_id`** (root goal id), never by assignment `loop_id`.
- One-shot migrate: if `jobs/{id}/rail_trace.jsonl` is missing and
  `loops/{id}/rail_trace.jsonl` exists, copy into the new path on first open.
- Postgres mode unchanged: tables still keyed by `job_id` (no new FS tree).

Supersedes IG-677’s “No `data/jobs/` tree” for **job soft-state only**.
Assignment runtime stays under `loops/`.

### 2. Wire — `autopilot_top` / `dag_snapshot` enrichment

Per goal node in `dag_snapshot` (and thus `top`):

| Field | Source |
|-------|--------|
| `steps_completed` / `steps_total` | Live `GoalNode.steps` when present; else report |
| `steps.nodes[]` | `{id, description, status, dependencies}` from `StepDAG` |
| `steps.edges[]` | Derived from `dependencies` |
| `created_at` | GoalNode ISO (job entry uses root) |

Job entry also carries root `created_at`. Loops already expose `started_at`.

Active goal filter unchanged (`TERMINAL_STATES`). In `mode=active`, terminal
StepDAG rows (`completed` / `failed` / `skipped`) are also omitted; `mode=all`
keeps the full step list. Goal `steps_completed` / `steps_total` counters stay
unfiltered.

### 3. CLI — linux-`top` viewport

| Item | Choice |
|------|--------|
| Alternate screen | `Live(..., screen=True, transient=True)` |
| Size | `console.size` each tick; pad body so footer sits on last row |
| Elapsed | `HH:MM:SS` from job `created_at` and loop `started_at` |
| Forest | Job → goal DAG → flat step list → active loops under goal |
| Quit | Ctrl+C restores prior terminal |

Example body:

```text
Autopilot top · running · pool 1/0/4 · 1 job(s) · 09:15:02
────────────────────────────────────────────────────────────────
[a1b2c3d4] active     pri=50  00:12:34  "Implement auth"
├─ [a1b2c3d4] active     "Implement auth"  steps 1/4
│  ├─ [UZH-01] completed  "Scaffold routes"
│  ├─ [UZH-02] pending    "Add JWT"
│  │  └─ loop autopilot__a1b2…  active  #3  00:03:21
│  └─ [UZH-03] pending    "Write tests"
└─ [e5f6aaaa] pending    "Write e2e"  steps 0/2
────────────────────────────────────────────────────────────────
q Quit · h Help · a All · s Steps · … · refresh 1s
```

Footer/bindings above reflect the IG-688 keymap polish; IG-686 shipped
fullscreen + StepDAG nesting with Ctrl+C-only quit.

### Out of scope (this IG)

Textual fullscreen, push via `autopilot_subscribe`, Postgres rail_trace
schema changes. Interactive keys / `--all` / scroll → [IG-688](IG-688-autopilot-top-interactive-keymaps.md).

---

## Implementation plan

1. **Host** — `trace_root = …/jobs`; migrate helper; `dag_snapshot` embeds steps;
   `top_snapshot` / `build_top_job_entry` pass `created_at`.
2. **CLI** — fullscreen Live; elapsed helper; nest step tree in
   `_format_top_forest`; width/height from `Console.size`.
3. **Docs** — this IG; note path change vs IG-RQJ-02 / IG-679.
4. **Tests** — rail path + migrate; snapshot steps; CLI render nest + elapsed;
   fullscreen flag smoke if useful.
5. **Verify** — cleanse → `./scripts/verify_finally.sh` → fix.

---

## Acceptance

- [x] Rail JSONL under `data/jobs/{job_id}/`; legacy `loops/{job_id}/` migrated
- [x] `dag_snapshot` / `top` include planned step DAG + live step counts
- [x] `soothe autopilot top` uses alternate screen; elapsed `HH:MM:SS`
- [x] Forest shows goal DAG with flat step list and loops
- [x] Unit tests green; `./scripts/verify_finally.sh` green

---

## Key files

| Area | Path |
|------|------|
| IG | `docs/impl/IG-686-autopilot-job-artifacts-and-top-polish.md` |
| Trace store | `packages/soothe/src/soothe/autopilot/rail/trace_store.py` |
| Service | `packages/soothe/src/soothe/autopilot/service.py` |
| Top helpers | `packages/soothe/src/soothe/autopilot/top_snapshot.py` |
| CLI | `packages/soothe-cli/src/soothe_cli/cli/commands/autopilot_cmd.py` |
| Spec | `docs/specs/RFC-228-autopilot-job-ipc.md` (§autopilot_top sample) |
