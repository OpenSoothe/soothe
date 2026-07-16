# IG-659: Turn-ID Event Boundary (Phases 1–5)

**Created**: 2026-07-16
**Status**: Complete
**Related**: IG-658 (client peel / progress gate), IG-556 (stream termination), RFC-450, RFC-614
**Incidents**: loops `d828`, `3e43`

---

## Goal

Make goal/turn stream boundaries **explicit on the wire** so prior-goal terminals
cannot close the next TUI turn. Heuristics (IG-658) remain as defense in depth.

## Phases

| Phase | Change | Status |
|-------|--------|--------|
| 1 | `turn_id` on `status=running` and turn-scoped `stream.end` / idle | Done |
| 2 | Stamp all loop-scoped frames with `turn_id` + monotonic `seq` | Done |
| 3 | Stop per-goal subscription `complete` on long-lived `loop_events` | Done |
| 4 | Finalize barrier: next admit waits until prior turn finishes terminals | Done |
| 5 | Client drops `seq <= last_turn_end_seq` and mismatched `turn_id` | Done |

## Wire

```text
turn_id = "{loop_id}:{generation}"   # generation from QueryEngine._loop_turn_generation
seq     = monotonic int per loop (daemon-assigned)

status { state: running|idle, loop_id, turn_id, seq? }
event  { loop_id, turn_id, seq, mode, data }
soothe.stream.end data { scope: turn, turn_id, ... }
```

## Client rules

1. Clear `expected_turn_id` at turn start; bind from `status=running`.
2. Ignore frames with `turn_id` ≠ expected (when both set).
3. Ignore frames with `seq <= last_turn_end_seq` after a completed turn.
4. Honor turn-end only when `turn_id` matches (fallback: IG-658 progress gate).

## Daemon notes

- `_loops_finalizing` is set before admission release so the next admit cannot
  race mid-drain / stream.end / idle.
- `_admit_query` also rejects while finalizing (`LOOP_BUSY`).
- Long-lived `loop_events` stays open; turn end is `stream.end` + `idle` only.

## Non-goals

- Per-turn WebSocket resubscribe (optional later).
- Requiring `goal_id` before Pass1 (use turn_id as primary).
