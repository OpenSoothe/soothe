# IG-671: Loop 2973 — TUI "Stream ended unexpectedly" after successful goal

**Created**: 2026-08-01
**Status**: Implemented
**Incident**: loop `2973` (`019fbd98-369f-7303-bd00-a4aa72cd2973`)

---

## Problem

Goal completed cleanly (`status=done`, `progress=complete`, worker
`turn_completed=True`), but the Ctrl+T plan panel footer showed
**Stream ended unexpectedly**.

Root cause: stream-end safety net treated any non-empty
`_current_step_messages` as in-flight. Late display-card registration
re-inserted already-completed step widgets into that registry, so
`finalize_pending_steps_with_error` called `goal_tree.set_interrupted(...)`
and overwrote the success footer from `set_loop_finished`.

Secondary: runner overwrote successful step summaries with
`Error: {first_tool_error}` whenever recoverable tool errors were present,
so transcript/frozen cards showed alarming `Error: Error: …` text with
`step_success=True`.

## Fix

1. Stream-end safety net: only interrupt truly `running` step cards / pending
   tools; never clobber a terminal success footer; silently drop stale
   completed registry entries.
2. Card registry: do not re-register completed step widgets; pop on card
   finalize.
3. Runner step_completed: keep `output_preview` when `success=True`; only
   prefix `Error:` when the step failed.

## Cleanse

- Shared `_clear_adapter_step_tool_registry` for finalize / interrupt /
  stream-end stale drops (no parallel clear sequences).
- Stream-end calls tool finalize only when tools remain; goal-footer interrupt
  happens once via step finalize.
- Merged overlapping stream-end unit modules into
  `test_stream_end_pending_error.py`.

## Acceptance

- [x] Successful goal leave plan panel success footer intact at stream end
- [x] Stale completed `_current_step_messages` do not trigger stream-end error UX
- [x] Successful steps with recoverable tool errors keep `Done [N tools]` summary
- [x] Unit tests cover stream-end + summary paths
- [x] `./scripts/verify_finally.sh` green for owned packages
