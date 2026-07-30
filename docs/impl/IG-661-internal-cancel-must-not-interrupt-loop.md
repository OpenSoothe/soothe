# IG-661: Internal CancelledError must not interrupt a running loop

**Created**: 2026-07-30
**Status**: Implemented
**Related**: IG-658 (loop b15e stream-end UX), incident `b15e` LBU-02 hop 4

---

## Problem

An internal `asyncio.CancelledError` (no user Esc/`/cancel`, no `cancel_event`) was
treated as a cooperative cancel: `goal_interrupted`, `stream.end reason=cancelled`,
worker terminal `cancelled`, and TUI cancel UX — stopping in-flight loop work.

## Fix

1. **Daemon** (`stream_cancel.py`): poll-cancel only when `cancel_event` is set (logged);
   retry stream once on unexpected `CancelledError`; exhausted unexpected → `RuntimeError`
   / error terminal, never cancel terminal.
2. **Thread + process workers**: wire the helper; map leaked `CancelledError` via
   `cancel_event` (cancelled vs error); keep worker thread alive on escaped cancel.
3. **StrangeLoop runner**: mark `goal_interrupted` only when `task.cancelling() > 0`.

## Verification

- Unit: `test_stream_cancel.py` (retry, cooperative, exhausted → error).
- `./scripts/verify_finally.sh`

## Cleanse

- Single cancel-reason helper in `soothe_client.stream_terminal`.
- CLI no longer re-parses STREAM_END reasons (DaemonSession is source of truth).
- Worker `stream_cancel` imports hoisted; unexpected-cancel error string deduped.
