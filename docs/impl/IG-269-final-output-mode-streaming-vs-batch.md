# IG-269: Final Output Mode Control (Streaming vs Batch)

**Status**: In Progress  
**Date**: 2026-04-27  
**Related**: IG-260, IG-268

## Goal

Fix missing final report output in headless CLI and add a client-side config switch to control final report rendering mode:

- `streaming` (default): render from `soothe.output.final_report.streaming`
- `batch`: render from `soothe.cognition.agent_loop.completed.final_stdout_message`

## Scope

- `soothe-cli` config model + loader support for final output mode
- `EventProcessor` routing policy for output events in CLI daemon path
- TUI direct streaming adapter parity for same mode behavior

## Notes

- Progress events (including `agent_loop.completed`) should continue to flow for status/goal cards.
- In `streaming` mode, batch final stdout should not duplicate streamed final output.
- In `batch` mode, streaming chunks should be suppressed and only final batch output displayed.
