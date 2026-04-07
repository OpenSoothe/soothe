# IG-060: Per-Thread Input History

## Problem

The daemon stores `input_history` (UP/DOWN arrow navigation) as a single global `InputHistory` instance (`d._input_history`). When a thread is resumed via `/resume`, the daemon sends this global history to the TUI, meaning all threads share the same input history regardless of which thread the user was actually typing in.

## Root Cause

- `d._input_history` in `server.py` is a single `InputHistory` shared across all threads
- `_handle_new_thread` creates a new global `InputHistory()` instance
- `_handle_resume_thread` sends `d._input_history.history` which is global, not per-thread
- `ThreadState` has an `input_history` field but it's never populated or used
- `query_engine.py` writes to `d._input_history` (global) instead of per-thread state

## Fix

1. Populate `ThreadState.input_history` on thread creation and resume
2. Route input adds through per-thread state in `query_engine.py`
3. Send per-thread input history on resume
4. For `new_thread`, send empty input_history (no change needed)
5. For `resume_thread`, send `reg.input_history.history` instead of `d._input_history.history`

## Files Changed

- `src/soothe/daemon/thread_state.py` - add helper for per-thread InputHistory
- `src/soothe/daemon/message_router.py` - use per-thread history on resume
- `src/soothe/daemon/query_engine.py` - route to per-thread history
- `src/soothe/daemon/server.py` - remove global _input_history init
