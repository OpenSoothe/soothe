# IG-723: Remove `autonomous` / `max_iterations` wire params

**Status**: Done  
**Related**: RFC-222 (Autopilot owns multi-goal), RFC-450 (daemon protocol)

## Goal

Remove inert per-request wire fields `autonomous` and `max_iterations` from
`loop_input` / `job_create` and the runner envelope. Iteration budget is
config-only: `agent.loop.max_iterations`.

Also remove related wire-compat shims for the old solo/autopilot mode flag.

## Why

- `autonomous` no longer selects a distinct runner path (Phase D removed
  `_run_autonomous`); Autopilot uses `autopilot_job`.
- Per-request `max_iterations` was gated behind `autonomous` and duplicated
  the shared StrangeLoop config ceiling.
- `autopilot_mode: "solo"` on `loop_new` / subscribe was a deprecated constant
  with no runtime consumers.

## Keep

- `agent.loop.max_iterations` (YAML / process config)
- StrangeLoop / `LoopState.max_iterations` (runtime from config)
- Stream phase name `autonomous_goal` (unrelated identifier)

## Done

- Removed from daemon schemas, queue options, query engine, `LoopRunRequest`
- Removed `DEPRECATED_LOOP_AUTOPILOT_MODE` / `autopilot_mode` from loop_new and
  subscribe responses; clients no longer inject the field
- CLI / Python / Go / TS / Rust clients no longer send or expose the removed
  options; deleted Go `WithAutonomous` and TS `interactive` deprecated field
- Examples and tests no longer exercise the removed APIs
