# IG-341: TUI in-process stream config includes thread workspace

## Problem

In-process TUI (`execute_task_textual` with `daemon_session is None`) calls `build_stream_config()`, which only set `configurable.thread_id`. Runnable config had no `workspace`, so `WorkspaceContextMiddleware` and IG-340 task-tool injection could not see the project directory — explore and filesystem tools fell back to resolver defaults.

## Fix

1. Add optional `workspace` to `build_stream_config`; resolve to an absolute path and set `configurable["workspace"]`.
2. Pass `workspace=self._cwd` from `SootheApp` into `execute_task_textual` (same effective directory as daemon bootstrap and status bar).

## Status

- [x] Implementation
- [x] Verification
