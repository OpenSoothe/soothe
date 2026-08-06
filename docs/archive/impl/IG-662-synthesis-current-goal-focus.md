# IG-662: Goal-Completion Synthesis Focuses on Current Goal

**RFCs**: RFC-214 (ledger projection), RFC-219 (goal completion), RFC-616 (scenario synthesis)
**Related**: IG-542 (execute Slice A), IG-555 (prior completion bias), IG-652 (synthesis Markdown)
**Status**: Implemented

---

## Goal

In multi-goal loops, goal-completion reports must primarily answer the **current**
goal. Prior goals appear only as brief status references — not as verbose
reprints of earlier completion reports or prior-goal execute evidence.

## Motivation

`loop_messages` is append-only across goals on the same loop. Plan and execute
already isolate segments:

| Phase | Prior goals | Current goal |
|-------|-------------|--------------|
| Plan mid_goal / assess | Compact terminal + IG-555 boundary | Current segment |
| Execute Slice A | K prior completion units | Current execute |
| **Synthesis (before)** | **All prior `execute_step` rows** | Mixed with current |

`project_loop_messages_for_synthesis` filtered by `phase="execute_step"` only —
no `_current_goal_segment_start` cut — so the synthesis model rehashed prior
goals. System/TASK prompts also lacked a multi-goal focus rule.

## Design

1. **Segment scope** — Project only `execute_step` rows after the last prior-goal
   terminal AI (`goal_completion` / `goal_interrupted`).
2. **Compact prior status** — When a prior terminal exists, prepend **one**
   compacted terminal unit with:
   - synthesis-specific `<PRIOR_GOAL_CONTEXT role="status_reference">` boundary
   - truncated AI body (preview chars) so status can be referenced without
     reprinting the full prior report
3. **Prompt rule** — System + TASK: focus on the current request; prior goals at
   most one short status mention; do not reprint prior reports.

## Files

- `sloop/prompts/plan_ledger_projection.py` — synthesis projection
- `prompts/fragments/instructions/synthesis_report_system.xml` — multi-goal rules
- `sloop/prompts/user_message.py` — TASK bullet for current-goal focus
- `sloop/engine/synthesis_projection.py` — module docstring
- Unit tests: ledger projection + synthesis system/TASK prompts

## Cleanse (related dead code)

- Removed no-op `_enrich_prior_goals` (completion text already comes from CE/ledger)
- Removed `_render_prior_goals_section` (full `completion_text` wall); mid-goal and
  new-goal plan envelopes both use `_render_prior_goals_tree` (truncated / ledger pointer)
- Updated stale synthesis docstrings that implied unscoped execute-ledger injection

## Validation

- `./scripts/verify_finally.sh`
