# IG-636: Background execution log observability (phase 2)

## Goal

Make `run_background` jobs observable by capturing stdout/stderr to a log file and returning `log_path` for agents to inspect via `read_file`.

## Scope

1. `ExecutionToolsConfig.background_log_dir` (optional override).
2. Default log dir: workspace `.soothe/background`, else virtual/home soothe background dir.
3. `run_background` returns `{pid, status, message, log_path}`.
4. Unit tests for log path wiring and file capture.

## Out of scope

Log tail tool, auto-cleanup on kill, streaming sync stdout.

## Verification

- `./scripts/verify_finally.sh`

## Status

**Complete.** Phase 4 deferred (log-tail tool, retention policy, sync streaming).
