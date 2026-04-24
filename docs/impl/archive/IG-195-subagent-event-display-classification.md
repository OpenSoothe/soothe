# IG-195: Subagent event display (classification + Claude started)

## Problem

- `classify_event_to_tier()` treated `soothe.capability.*` as domain `capability`, which had no default mapping → **DEBUG**, so `EventProcessor` hid all capability progress from normal verbosity.
- Legacy `soothe.subagent.*.dispatched|completed|judgement` were classified as domain `subagent` → **DETAILED**, inconsistent with `StreamDisplayPipeline` intent and failing tests.

## Solution

1. **SDK `classification.py`**: Before generic domain lookup, handle `soothe.capability.*` via `is_subagent_progress_event()` (NORMAL vs DETAILED) and legacy `soothe.subagent.*` milestones via a small predicate (NORMAL).

2. **Claude subagent**: Add `soothe.capability.claude.started`, register as NORMAL, emit once when a Claude run begins; add to `SUBAGENT_PROGRESS_EVENT_TYPES` so dispatch shows like browser.

## Verification

`./scripts/verify_finally.sh`
