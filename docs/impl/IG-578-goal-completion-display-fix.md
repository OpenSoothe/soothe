# IG-578: Goal Completion Display Fix

**RFC**: [RFC-631](../specs/RFC-631-goal-display-snapshots.md), [RFC-614](../specs/RFC-614-loop-assistant-output-phases.md)  
**Created**: 2026-07-12  
**Status**: Implemented

## Summary

Fix misleading end-of-goal transcript text (planning narration after a completed
task) by separating assistant phases in the display ledger, freezing snapshots from
`goal_completion` wire text only, persisting streamed synthesis tails, and
reconciling weak synthesis against execute-step deliverables.

## Problem (loop d1de)

1. **`freeze_goal_display`** used unfiltered `full_response`, which mixed
   `plan_direct` / tool / non-terminal chunks — `goal_completion` metadata showed
   planning prose without the numeric answer.
2. **`card_binder._append_assistant_text`** merged consecutive assistant cards
   across phase boundaries (`execute_step` / `plan_direct` / `goal_completion`).
3. **`ThreadLogger`** skipped `AIMessageChunk` rows, so streamed synthesis never
   reached `conversation.jsonl` for resume replay.
4. **Synthesis** sometimes emitted forward-looking planning text while step ledger
   already held the deliverable (e.g. `3632`).

## Changes

| Area | Fix |
|------|-----|
| `soothe_daemon/query/engine.py` | Accumulate `goal_completion` phase text separately; freeze uses it with ledger fallback (no mixed `full_response`) |
| `soothe_sdk/display/card_binder.py` | Phase-aware assistant merge via `loop_output_phase` on `MessageData` |
| `soothe_sdk/display/transcript_types.py` | Add optional `loop_output_phase` field |
| `soothe/logging/thread_logger.py` | Accumulate `goal_completion` chunks; persist on stream terminal |
| `soothe/.../goal_completion_output.py` | Reconcile synthesis with execute-step deliverables (numeric + token overlap) |
| `soothe/.../nodes/goal_completion.py` | Apply reconciliation before ledger append |

## Non-goals

- Changing CognitionReason card content (plan reasoning remains visible by design)
- Skipping synthesis for all single-step goals (only fallback when deliverable drift)

## Verification

- `./scripts/verify_finally.sh`
- Unit tests in `soothe-sdk`, `soothe`, `soothe-daemon` packages
