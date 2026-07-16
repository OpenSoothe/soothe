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

**Loop 3e43 variant**: goal 0's TUI finishes early on `strange_loop.completed`,
user submits goal 1, then goal 0's stream finally drains and emits
`stream.end`/`complete` *after* goal 1 already saw `status=running` + intake
`plan.phase`. IG-658 peel alone is insufficient; ownership must be re-checked
after drain, and the client must require real progress before honoring turn-end.

## Fix

1. Peel subscription `complete` and turn-end custom events from `_pending_events`
   at turn start.
2. In `iter_turn_chunks`, ignore turn-end customs until `status=running`
   (`query_started`) so late wire frames cannot close a turn that has not begun.
3. **Loop 3e43 follow-up**: ignore turn-end until real turn progress
   (messages / step / plan.created) — intake-only `plan.phase` is not enough.
4. **Daemon**: drain first, then re-check `_owns_turn` before emitting
   `stream.end` / `idle`, so a successor admit mid-finalize cannot leave the
   prior turn's terminals on the shared subscription.

**Follow-up**: [IG-659](IG-659-turn-id-event-boundary.md) stamps `turn_id` +
`seq` on the wire and removes per-goal subscription `complete`.

## Verification

- Unit: peel terminal frames; ignore pre-start `stream.end`; still end after
  `running` + legitimate `stream.end`.
- Unit: ignore `stream.end` after intake-only plan.phase; accept after step.
- Manual: two sequential TUI queries on one loop; second shows plan/steps.

## Cleanse

- Shared vocabulary in `soothe_client/stream_terminal.py` (SDK `STREAM_END` /
  `STRANGE_LOOP_COMPLETED`): peel labels, turn-end detection, drop/ack checks,
  turn-progress gate.
- Removed duplicate frozensets / classmethod peel labeling on `WebSocketClient`.
- Removed CLI `_StubEventClient` partial peel reimplementation (it incorrectly
  filtered the live turn sequence; peel is covered on `WebSocketClient`).
