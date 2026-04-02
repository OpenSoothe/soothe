# IG-124: SOOTHE_HOME runs/loop and canonical thread IDs

## Status

Completed (verification passed).

## Goal

1. Store run artifacts and loop working-memory spill under `$SOOTHE_HOME` (`runs/`, `loop/`), not `{workspace}/.soothe/`.
2. Use the durability thread identifier for `runs/{thread_id}/`, not synthetic IDs like `thread-1__goal_G_1`.
3. Keep LangGraph `configurable.thread_id` isolated for parallel goals/steps via optional `RunnerState.langgraph_thread_id`.

## Changes

- `RunArtifactStore`: always `SOOTHE_HOME/runs/{thread_id}/`; absolute paths for framework writes; coarse lock per run dir for parallel goals.
- `LoopWorkingMemory`: spill under `SOOTHE_HOME` / `spill_subdir` (default `loop`).
- Autonomous parallel goals: canonical `thread_id` on runner state; `langgraph_thread_id` = former composite when needed.
- Parallel plan steps: same pattern for step isolation.

## Verification

`./scripts/verify_finally.sh`
