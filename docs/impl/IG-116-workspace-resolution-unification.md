# IG-116: Unified workspace resolution for streams

## Status

Completed.

## Goal

One precedence chain for resolving the directory passed to `SootheRunner.astream(..., workspace=...)`, daemon thread registry, and `SootheConfig.workspace_dir`, so Reason/Act, LangGraph `configurable["workspace"]`, and filesystem tools stay aligned.

## Design

- **Module**: `soothe.core.workspace_resolution.resolve_workspace_for_stream` returns `ResolvedWorkspace(path, source)`.
- **Precedence**: explicit API arg → per-thread registry path → daemon installation default → expanded `workspace_dir` → `cwd`.
- **Runner**: Always resolves before subagent / autonomous / agentic paths; logs one DEBUG line per `astream` with `thread_id`, `path`, `source`.
- **Daemon**: `QueryEngine` uses the same helper with `thread_workspace` + `installation_default` + config fallback.
- **RFC-104**: `_collect_context_for_injection` uses `FrameworkFilesystem` ContextVar first, then falls back to `RunnerState.workspace` for git status and prompt injection when the var is unset.

## Reason-phase prompt (Layer 2)

`build_loop_reason_prompt` injects `<WORKING_DIRECTORY>` when `PlanContext.workspace` is set so the Reason model does not ask for a project path for in-workspace goals.

## Follow-up (pre-stream and derived states)

- **`PhasesMixin._ensure_runner_state_workspace`**: If `RunnerState.workspace` is missing or blank, fill via `resolve_workspace_for_stream(config_workspace_dir=...)`.
- **Call sites**:
  - Start of `_pre_stream_independent` so thread lifecycle + `_collect_context_for_injection` + `_pre_stream_planning` share one directory.
  - `_execute_step` after building `step_state` (inherits parent then ensure).
  - `_execute_autonomous_goal` after building `iter_state` (inherits `parent_state` then ensure).

## Verification

`./scripts/verify_finally.sh`
