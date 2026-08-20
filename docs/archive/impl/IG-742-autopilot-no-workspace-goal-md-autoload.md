# IG-742: Autopilot Submit — No Workspace GOAL.md Autoload

**Created**: 2026-08-14  
**Status**: Implemented  
**Related**: [IG-702](IG-702-autopilot-job-goal-md-artifact.md),
[RFC-230](../specs/RFC-230-job-maturity-assessment.md)

---

## Goal

Stop treating a workspace-tree `GOAL.md` as the job acceptance contract unless
the operator explicitly passes it via `--file`. Inline `TASK` submits and
maturity / QA briefs must use only the durable job artifact
`$SOOTHE_DATA_DIR/jobs/{job_id}/GOAL.md`.

## Problem

| Issue | Before |
|-------|--------|
| CLI default | `soothe autopilot submit` with no args read `./GOAL.md` |
| Maturity / QA | `load_goal_md_excerpt` preferred `{workspace}/GOAL.md` over the job artifact |
| Restart drift | Workspace file could change after submit; acceptance latched against a different contract than the submitted description |

## Design

1. **CLI**: Require exactly one of `TASK` or `--file` (`-` = stdin). No cwd
   `GOAL.md` default.
2. **Host**: Delete workspace-first `load_goal_md_excerpt`. Maturity assessor
   and `acceptance_contract_brief` read only `load_job_goal_md` (job artifact).
3. **Restart**: Acceptance text is the snapshot written at root submit
   (IG-702); daemon restart cannot pick up an unrelated workspace file.

## Acceptance

- [x] Bare `soothe autopilot submit` errors even when `./GOAL.md` exists
- [x] Inline TASK does not feed workspace `GOAL.md` into maturity / QA briefs
- [x] Job artifact remains the sole GOAL.md source for acceptance
- [x] Dead `source_file` plumbing removed (`submit_task` / `intake_goal` /
      `GoalNode.source_file` / CLI show); contract SoT is job `GOAL.md`
- [x] `./scripts/verify_finally.sh` green
