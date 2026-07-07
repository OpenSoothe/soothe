# IG-110: Daemon State Isolation and Module Refactoring

## Status

In progress — implements multi-session bug fixes and daemon modularization per plan.

## Problem

IG-109 cleared `runner._current_thread_id` on cancel but shared mutable state on `SootheRunner` and daemon globals (`_current_plan`, artifact store, per-thread loggers) still leaked across queries.

## Solution Summary

1. **Runner**: Scope `artifact_store` on `RunnerState`; stop mutating `self._current_thread_id` inside `_pre_stream_independent`; use `state.plan` in step loop; sync/clear `self._current_plan` for CLI; clear query-scoped state when `astream` completes.
2. **ThreadExecutor**: Do not call `set_current_thread_id`; `astream(thread_id=...)` is sufficient.
3. **Daemon**: `ThreadStateRegistry` for per-thread loggers/history/drafts; `QueryEngine` + `MessageRouter`; `SootheRunner` public thread APIs to avoid `_durability` access from daemon.
4. **Tests**: Regression and import updates.

## Verification

```bash
./scripts/verify_finally.sh
```

## References

- Prior attempt: [IG-109](IG-109-daemon-cancel-state-reset.md)
- Plan: Daemon State Isolation Bug Fix and Module Refactoring (Cursor plan)
