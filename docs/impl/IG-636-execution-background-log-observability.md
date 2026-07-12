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

## Cleanup

- Dropped unused ``current_run_dir`` fallback (ContextVar is never set).
- Consolidated ``run_background`` error payloads via ``_background_run_error()``.
- Merged config test into ``test_execution_run_background.py``.
