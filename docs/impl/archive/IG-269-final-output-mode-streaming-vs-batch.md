# IG-269: Final Output Mode Control (Streaming vs Batch)

**Status**: In Progress  
**Date**: 2026-04-27  
**Related**: IG-260, IG-268

> **Update (IG-317):** Streaming vs batch applies to **goal-completion (and related) `messages` chunks** with `phase`, not to removed `soothe.output.final_report.streaming` custom events.

## Goal

Fix missing final report output in headless CLI and add a client-side config switch to control final report rendering mode:

- `streaming` (default): render incrementally from loop-tagged **`messages`** (`phase` includes goal completion / final report phases)
- `batch`: defer visible assistant text until non-chunk / final `messages` handling (see `EventProcessor` goal-completion path)

## Scope

- `soothe-cli` config model + loader support for final output mode
- `EventProcessor` routing policy for output events in CLI daemon path
- TUI direct streaming adapter parity for same mode behavior

## Notes

- Progress events (including `agent_loop.completed`) should continue to flow for status/goal cards.
- In `streaming` mode, batch final stdout should not duplicate streamed final output.
- In `batch` mode, streaming chunks should be suppressed and only final batch output displayed.
