# IG-658: Stale Turn-End Frames Blank Second-Query TUI

**Created**: 2026-07-16
**Status**: Complete
**Incident**: loop `d828` (`019f68fa-6600-7320-a20f-145169fbd828`) — second query TUI no activity

---

## Problem

After goal 0 completes, a leftover terminal frame (`soothe.stream.end` /
`strange_loop.completed`, optionally subscription `complete`) can remain in the
Python client's `_pending_events` (or arrive on the wire before the new turn's
`status=running`). On the next `loop_input`, `iter_turn_chunks` treats that
frame as the current turn end → TUI `turn_finished` in ~0.3s with
`status=no_events` while the daemon worker continues executing.

`peel_stale_pending_control_events` only removed handshake/card-replay types,
not terminal frames.

## Fix

1. Peel subscription `complete` and turn-end custom events from `_pending_events`
   at turn start.
2. In `iter_turn_chunks`, ignore turn-end customs until `status=running`
   (`query_started`) so late wire frames cannot close a turn that has not begun.

## Verification

- Unit: peel terminal frames; ignore pre-start `stream.end`; still end after
  `running` + legitimate `stream.end`.
- Manual: two sequential TUI queries on one loop; second shows plan/steps.

## Cleanse

- Shared vocabulary in `soothe_client/stream_terminal.py` (SDK `STREAM_END` /
  `STRANGE_LOOP_COMPLETED`): peel labels, turn-end detection, drop/ack checks.
- Removed duplicate frozensets / classmethod peel labeling on `WebSocketClient`.
- Removed CLI `_StubEventClient` partial peel reimplementation (it incorrectly
  filtered the live turn sequence; peel is covered on `WebSocketClient`).
