# IG-161: Handle `/cancel` Outside the Daemon Input Queue

**Status**: Completed  
**Created**: 2026-04-13  

## Problem

The daemon `_input_loop` awaits `run_query()` for each `"input"` message before calling `_current_input_queue.get()` again. Client `/cancel`, `/exit`, and `/quit` were enqueued like other commands, so they were not processed until the current query finished—Ctrl+C and detach appeared broken while a query ran.

## Approach

In `MessageRouter.dispatch()`, when `type == "command"` and the normalized command is:

- `/cancel` — call `daemon._query_engine.cancel_current_query()` when the engine exists; **do not** enqueue.
- `/exit` or `/quit` — broadcast `{"type": "status", "state": "detached"}` (same as `_input_loop`); **do not** enqueue.

Other commands continue to use `_current_input_queue` unchanged. Matching is case-insensitive with `strip()`.

## Files

| File | Change |
|------|--------|
| `src/soothe/daemon/message_router.py` | Branch for `/cancel` → direct `cancel_current_query()` |
| `tests/unit/test_cli_daemon.py` | Tests: cancel bypasses queue; non-cancel still enqueues |

## Verification

`./scripts/verify_finally.sh`
