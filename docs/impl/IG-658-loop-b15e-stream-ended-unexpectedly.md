# IG-658: Loop b15e — TUI "Stream ended unexpectedly" on cancelled turn

**Created**: 2026-07-30
**Status**: Implemented
**Incident**: loop `b15e` (`019fb202-f43a-73b1-91af-978e61b5b15e`) goal 1 (LBU-02)

---

## Problem

During goal 1 step `LBU-02`, the worker hit `asyncio.CancelledError` mid-LLM hop.
The TUI finalized the in-flight step as **"Stream ended unexpectedly"** even though
the daemon cancel/finalize path was active. Side issues from the same turn:

1. Worker `cancelled` terminal with `payload=None` was treated like a clean stream end
   (no `CancelledError` raised to QueryEngine → weak `turn_cancelled` / reason wiring).
2. CLI only sets `last_turn_cancellation_seen` from `"Cancellation requested"` command
   text — not from `soothe.stream.end` `reason=cancelled`.
3. `TuiDaemonSession` lacks `aupdate_loop_state` → token persist / interrupt cleanup
   AttributeError.
4. Interrupted loop metadata stayed `status=running` until 180s reconciliation.
5. Worker thread exited after the cancelled request (`exiting after 1`) and was respawned.

## Fix

1. Thread pool: raise `CancelledError` for `cancelled` terminals; harden worker so one
   failed/cancelled request cannot kill the thread.
2. Client + CLI: honor `stream.end` cancel reasons for stream-end UX.
3. Client: implement `aupdate_loop_state` → `loop_state_update`.
4. Runner interrupt touch: set loop metadata `status=idle`.

## Follow-up (IG-661)

Internal `CancelledError` without `cancel_event` must **not** interrupt the loop:
retry once, then error terminal — never cooperative cancel / `goal_interrupted`.
