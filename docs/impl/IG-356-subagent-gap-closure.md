# IG-356 — Subagent gap closure (final prose, planner evidence, parallel delegates)

## Purpose

Close remaining gaps from Ask-mode gap analysis after IG-355:

1. **Explore final UX** — Emit user-facing markdown from structured `ExploreResult` instead of raw JSON only (parity with Claude-like prose finals).
2. **Planner evidence** — Carry bounded `delegate_evidence_preview` in outcomes (`task` metadata + wave `StepResult`) so `StepResult.to_evidence_string()` reflects delegate output, not only “delegation completed”.
3. **Parallel waves** — When multiple steps run in parallel and each yields `task` delegate finals, merge ordered delegate bodies into `last_execute_assistant_text` (separator `---`) instead of clearing assistant text entirely.

## Status

Completed (pending CI verification).

## Verification

Run `./scripts/verify_finally.sh` before merge.
