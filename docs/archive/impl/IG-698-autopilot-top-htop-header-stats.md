# IG-698: Autopilot `top` htop-Style Header Stats

**Created**: 2026-08-06  
**Status**: Implemented (header meter/status color polish: progress green vs util load)  
**Related**: [IG-679](IG-679-autopilot-top-command.md),
[IG-686](IG-686-autopilot-job-artifacts-and-top-polish.md),
[IG-688](IG-688-autopilot-top-interactive-keymaps.md),
[RFC-228 §autopilot_top](../specs/RFC-228-autopilot-job-ipc.md)

---

## Executive Summary

Replace the thin `soothe autopilot top` header (pool + job count + color legend)
with an **htop-style** summary: meter bars and by-status counts for Jobs,
Goals, and Loops (plus Steps when present), plus oldest-job uptime.

---

## Design

- **CLI-only aggregation** from the existing `autopilot_top` forest (no wire
  change). Counts match what the body shows (`mode=active` vs `mode=all`).
- Header rows: title (state + clock + `up HH:MM:SS`) → Jobs / Goals / Loops
  meters → optional Steps → view flags → rule. Drop the separate legend line.
- Meter fill: **util** (Jobs active, Loops pool) green → yellow → red under
  load; **progress** (Goals when metering completed, Steps) yellow → green,
  with full completion **bright green** (not util red).
- Status counts: `done=` / `completed` uses bold green (readable success).
- Pool line keeps `active/idle/max` and adds forest `assigned` loop count.

### Out of scope

Server-side `stats` block on `autopilot_top` (CE-wide totals while forest is
filtered). Desktop jobs UI.

---

## Implementation

| Piece | Location |
|-------|----------|
| `aggregate_top_stats`, meters, header | `soothe_cli.cli.commands.autopilot_cmd` |
| Unit tests | `packages/soothe-cli/tests/unit/cli/test_autopilot_top.py` |
