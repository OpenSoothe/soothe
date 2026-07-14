# IG-356 — Subagent gap closure (final prose, planner evidence, parallel delegates)

## Purpose

Close remaining gaps from Ask-mode gap analysis after IG-355:

1. **Explore final UX** — Emit user-facing markdown from structured `ExploreResult` instead of raw JSON only (parity with Claude-like prose finals).
2. **Planner evidence** — Carry bounded previews in outcomes: `task_return_preview` (per-tool metadata) and `wave_join_preview` (wave-level `StepResult`); unified via `planner_outcome_text_preview()` (IG-357 rename/clarity).
3. **Parallel waves** — When multiple steps run in parallel and each yields `task` delegate finals, merge ordered delegate bodies into `last_execute_assistant_text` (separator `---`) instead of clearing assistant text entirely.

## Status

Completed (pending CI verification).

## Verification

Run `./scripts/verify_finally.sh` before merge.
