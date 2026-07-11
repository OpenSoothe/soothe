# IG-577: Resume Transcript Display Hardening

**RFC**: [RFC-413](../specs/RFC-413-server-owned-display-card-ledger.md), [RFC-631](../specs/RFC-631-goal-display-snapshots.md)  
**Created**: 2026-07-11  
**Status**: Implemented

## Summary

Fix ill-formed loop resume transcripts in the TUI: strip orchestration-internal
checkpoint rows, drop standalone tool stubs, simplify step/subagent cards to
**tool-call count only** (no inline tool-row replay), and paint assistant bodies
on mount so cards are not dot-only until async hydration.

## Problem

1. **Missing card chrome / dot** — `MessageType.TOOL` restored as italic `AppMessage`
   (`[tool_name]`), not cognition cards.
2. **Empty assistant bodies** — `AssistantMessage.on_mount` refreshed the dot but
   deferred body render to an async drain queue.
3. **Internal ledger leak** — `intent_classify` (and related planning) checkpoint
   pairs were not in `_LOOP_INTERNAL_CHECKPOINT_PHASES`, surfacing JSON and
   `GOAL:/TASK:` envelopes on resume.
4. **Over-complex resume** — `_build_step_tool_rows_map` rebuilt full inline tool
   rows for step/subagent cards from activity logs; live UX already folds tool
   activity into step footers (`step_tool_call_count`).

## Changes

### Card binder (`soothe_sdk.display.card_binder`)

| Change | Rationale |
|--------|-----------|
| Expand `_LOOP_INTERNAL_CHECKPOINT_PHASES` with `intent_classify`, `plan_gap_analysis`, `continuation` | Align with core `planning_phases`; never surface on display ledger |
| Always strip internal checkpoint rows (not gated on cognition replay) | Resume must not depend on activity-log presence |
| Always suppress standalone `TOOL` cards in `convert_messages_to_data` | Tool activity = step footer count only |
| Remove `_attach_step_tool_rows` / `_build_step_tool_rows_map` from replay paths | Simplify resume; keep `step_tool_call_count` from `step.completed` events |
| Add `sanitize_resume_display_cards()` | Strip legacy `TOOL` cards and `step_tool_calls_json` at TUI fetch |

### TUI

| File | Change |
|------|--------|
| `_history.py` | Call `sanitize_resume_display_cards` after ledger fetch |
| `_messages_mixin.py` | Filter `MessageType.TOOL` before mount (belt-and-suspenders) |
| `assistant.py` | `_render_to_body()` in `on_mount` when content is preloaded |
| `_history.py` (`_consume_daemon_events_background`) | Skip internal-phase wire messages; only mount user-visible assistant phases |

### Tests

- Update card-binder tests: step cards carry `step_tool_call_count`, not `step_tool_calls_json`
- Add regression: `intent_classify` checkpoint rows dropped from `convert_messages_to_data`
- Remove tests for deleted `_build_step_tool_rows_map` replay attachment

## Non-goals

- Live streaming tool rows on step cards (unchanged — full rows during active turns)
- Scroll hydration within an active session still restores `step_tool_calls_json` when
  present in the in-memory store from the current turn

## Verification

- `./scripts/verify_finally.sh`
- Manual: `/resume` a multi-step loop — step cards show description + duration +
  `N tools` footer; no `[run_command]` stubs; no JSON intake blobs
