# IG-727: Stale Turn Reader Terminate + Ghost Follow-on Attach

## Problem

On follow-on goals (loop `96d9`), the TUI reader can bind to a leftover
prior-turn `status=running` (`:N`), ignore that turn's `stream.end` (progress
gate), then still exit on `status=stopped` (no progress gate). The daemon keeps
executing while the TUI is idle. A user re-submit then enqueues a duplicate
`loop_input`; when the live turn ends, the daemon starts the next goal with no
TUI consumer (ghost goal). Post-idle drain also swallows successor
`status=running`.

## Fix

1. **soothe-client**: completed-generation floor; refuse stale `running` bind;
   gate `stopped` like `idle`; peel pending `status=idle|stopped`; rebind on
   successor `running` during post-idle drain. Keep `DaemonSession` /
   `TurnBoundary` parity.
2. **soothe-cli**: before `send_turn`, attach-only if the loop is already live;
   after turn cleanup, re-attach with `skip_daemon_send_turn` when still live.

## Status

Done. Verified with `./scripts/verify_finally.sh` and client unit tests.
