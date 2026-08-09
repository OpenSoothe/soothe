# IG-702: Autopilot Job `GOAL.md` Artifact

**Created**: 2026-08-06  
**Status**: Implemented  
**Related**: [RFC-228](../specs/RFC-228-autopilot-job-ipc.md),
[RFC-230](../specs/RFC-230-job-maturity-assessment.md),
[IG-686](IG-686-autopilot-job-artifacts-and-top-polish.md),
[IG-692](IG-692-job-maturity-assessment.md)

---

## Goal

Persist each Autopilot **job** (root `GoalNode`) description as
`$SOOTHE_DATA_DIR/jobs/{job_id}/GOAL.md` so the submit contract is a durable
job artifact alongside `rail_trace.jsonl` / `rail_state.json`
(WavePlan fan-out lives in CE findings + `rail_state.wave_slices` — see
[IG-720](IG-720-waveplan-ce-findings-no-file.md); no `wave-plan.json` file).

## Problem

| Issue | Today |
|-------|--------|
| Job desc only in CE | `GoalNode.description` lives in persist KV; no filesystem snapshot under `jobs/{id}/` |
| Maturity gap | Assessor reads `{workspace}/GOAL.md` only; inline / `--file` submits without a workspace copy miss the contract body |
| Operator forensics | Inspecting `jobs/{id}/` shows rail soft-state but not the original job prompt |

## Design

### Disk layout (extends IG-686)

```text
~/.soothe/data/jobs/{job_id}/
  GOAL.md                 # NEW — submit description (UTF-8 markdown body)
  rail_trace.jsonl
  rail_state.json         # includes wave_slices when fan-out applied
```

- Write on **root** job create only (`parent_id is None`) in `submit_task`.
- Content = exact `description` string passed to submit (same text as CE).
- Path sanitization mirrors other job artifacts (reject `/`, `\`, `..`).
- Fail soft: log warning on I/O error; do not fail submit.
- Child / decomposed goals do **not** get their own `GOAL.md` under a separate tree.

### Maturity fallback (RFC-230)

`load_goal_md_excerpt` resolution order:

1. `{workspace}/GOAL.md` when present (operator workspace contract)
2. Else `jobs/{job_id}/GOAL.md` when `jobs_root` + `job_id` provided
3. Else empty

Assessor and acceptance briefs pass job identity so inline submits still feed
maturity without requiring a workspace copy.

### Out of scope

- Syncing CE description edits back to `GOAL.md` after submit
- Postgres-only blob (FS job tree remains soft-state home, same as rail_state)
- Writing `GOAL.md` for non-root goals

## Implementation plan

1. Helper module `soothe.autopilot.intake.contract` — resolve / write / load (IG-733; formerly `jobs/goal_md.py`)
2. `AutopilotService` retains `_jobs_root`; write after root `ensure_job`
3. Wire maturity + acceptance brief fallback
4. Unit tests for write-on-submit, path safety, maturity fallback
5. Inspect skill data-sources row for `GOAL.md`

Related: [IG-733](IG-733-autopilot-cognition-intake.md).

## Acceptance

- [x] Root submit writes `jobs/{job_id}/GOAL.md` with description body
- [x] Child submit does not write a job `GOAL.md` for the child id
- [x] Maturity excerpt falls back to job artifact when workspace has no `GOAL.md`
- [x] `./scripts/verify_finally.sh` green
