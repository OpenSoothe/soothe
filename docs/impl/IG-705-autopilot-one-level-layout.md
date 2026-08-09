# IG-705: Autopilot One-Level Layout + Workflow Tracing

## Goal

Clarify `soothe.autopilot` with one-level subpackages (no deeper nesting), a
restrained root public API, and consistent INFO/DEBUG tracing on main goal
lifecycle workflows.

## Constraints

- One-level subpackages only under `soothe.autopilot` (e.g. `soothe.autopilot.rail.*`
  is allowed; `soothe.autopilot.rail.foo.*` is not).
- No backward-compat shims for old flat import paths — update all in-repo importers.
- Keep `AutopilotService` as the root facade (`service.py`); do not split it in this pass.

## Target layout

```text
soothe/autopilot/
  __init__.py                 # AutopilotService, AutopilotMonitor only
  service.py

  intake/                     # GOAL.md contract + guidance absorb/collect (IG-733)
  prompts/                    # LLM fragments + builders (IG-736; like sloop.prompts)
  rail/                       # LoopRail runtime
  monitor/                    # AutopilotMonitor + models
  verify/                     # consensus, maturity, DAG health, backoff, verifiers
  workers/                    # pool, job loop index, workspace reservation
  dispatch/                   # goal-dispatch context store/projector/models
  jobs/                       # top snapshot + rail selection artifacts
  schedule/                   # cron helpers (tasks, timezone)
```

## Public API

Root `__init__.py` exports only:

- `AutopilotService`
- `AutopilotMonitor`

All other types are imported from their subpackage (e.g.
`soothe.autopilot.workers.pool`, `soothe.autopilot.dispatch.models`).
Subpackage `__init__.py` files re-export that subpackage's intentional surface.

## Workflow tracing checklist

| Workflow | Sites | Level |
|----------|-------|-------|
| Goal intake / planning | `submit_task`, `intake_goal`, rail bind, plan mirror | INFO summary; DEBUG step ids |
| Goal update / status | state_changed, step mirror, consensus finalize, maturity, status/top | INFO transitions; DEBUG per-step |
| Goal events | rail notify, emit completed/failed, bus handlers | INFO success; DEBUG no-rail |
| Core dispatch | try_dispatch, stream completion, worker acquire/release, dreaming | INFO dispatch/terminal; DEBUG defer |

Do not log full prompts or large evidence blobs at INFO.

## Verification

Run `./scripts/verify_finally.sh` after migration; fix import fallout until green.
