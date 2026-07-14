# IG-584: Execution tools stability (phase 1)

## Goal

Harden the four host execution tools (`run_command`, `run_python`, `run_background`, `kill_process`) with focused stability fixes and unit test coverage.

## Scope

1. **`kill_process`** — terminate process groups (SIGTERM → SIGKILL), reject invalid PIDs, align with `_kill_process_tree`.
2. **`run_python`** — clarify REPL persistence scope in tool description.
3. **Tests** — unit coverage for kill/background/python/run_command edge paths (mocked subprocess where possible).

## Out of scope

Background log files, streaming stdout, persistent shell sessions (phase 2).

## Verification

- `./scripts/verify_finally.sh`

## Status

**Complete.** Phase 4 deferred.
