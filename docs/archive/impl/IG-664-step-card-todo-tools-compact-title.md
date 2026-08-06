# IG-664: Step Card Todo/Tools Tree + Compact Title Meta

## Goal

Restructure cognition step cards so activity nests under **Todo** then **Tools**,
drop the Running footer line, and surface live status as a compact middot suffix
on the untruncated step title.

## Motivation

1. Users could not see in-step todo progress next to tool activity. Daemon
   execute avoids LangGraph ``updates`` (full state snapshots), so Todo must
   come from ``write_todos`` tool-call args on the step card wire path.
2. Flat tool/task lines under the title compete with the Running footer for the
   same stats (elapsed, tool counts, tokens).
3. Title space is scarce; meta must stay abbreviated while the step brief stays
   full (no truncation).

## Design

### Target layout

```text
● Scan Frontend and Backend · 45s · 12/1 · ↑8.1K ↓2.0K
⎿  TODO
⎿    ⠋ Survey frontend tree
⎿    ○ Survey backend tree
⎿    ○ Summarize findings
⎿  TOOLS
⎿    Deep Research(scan both trees) · 6 tools
⎿    ⠋ ListFiles(~/Workspace/Longan)
⎿    · +3 more tools
```

### Title meta (compact, description untruncated)

| Field | Form | Notes |
|-------|------|-------|
| Elapsed | `45s` / `1m5s` | Whole-second ticks; no spaces in `NmNs` |
| Counts | `12/1` | `total_tools` / `task_delegations` |
| Tokens | `↑8.1K ↓2.0K` | Only when either side > 0 |
| Retry | `↻1/3` | Only when retry attempt > 0 |

Omit stage text. Omit literal `Running...`. Glyph flash on the
title prefix remains the running affordance.

### Activity tree

1. **Todo** section (when non-empty) — CoreAgent todo items with status glyphs
   (`pending` hollow, `in_progress` spinner, `completed` check, error/cancel).
2. **Tools** section (when tool/task/notes activity exists) — prior
   `StepActivityTree` content (task markers + main tool preview + notes),
   indented under the section header.
3. Hide empty sections. Hide Running footer (`#step-cognition-status` while
   `running`); Completed/Failed/Pending footers stay for now.
4. Prefer not showing `write_todos` as a Tools preview line when the Todo
   section is populated from the same updates.

### Data path

Daemon / execute streaming does **not** emit a dedicated todos channel:
``stream_mode=updates`` is avoided during execute (IG-477; full state snapshots),
and ``write_todos`` only logs server-side.

**Source of truth for the Todo section:** ``write_todos`` tool-call args on the
step card wire path:

1. Host ``filter_redundant_stream_tool_updates`` **keeps** ``write_todos`` updates
   (same exception as ``task``) so complete todo payloads are not dropped.
2. CLI ``apply_tool_call_wire_update`` / ``add_tool_call`` /
   ``update_tool_args`` call ``set_todos`` / ``_maybe_apply_write_todos_args``.

**Note:** The Todo section only appears when CoreAgent actually calls
``write_todos``. Simple explore steps often never call it — empty section is
hidden by design.

## Files

- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/cognition_step.py`
- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/cognition_step_activity.py`
- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`
- `packages/soothe-cli/tests/unit/ux/tui/test_step_card_*.py`
- `docs/specs/RFC-628-step-card-display-refactor.md` (Activity Tree / header notes)

## Acceptance

- [x] Step title shows full description + compact `· elapsed · N/M · ↑… ↓…`
- [x] No `Running...` footer while step is running; timer refreshes title meta
- [x] Todo section above Tools; empty sections hidden
- [x] `write_todos` tool args on the step card paint/refresh Todo children with status glyphs
- [x] Existing tool/task preview and footer Done/Failed behavior preserved
- [x] Unit tests updated; `./scripts/verify_finally.sh` green

## Out of scope

- Desktop step card parity
- Folding Pending/Done/Failed footers into the title

## Cleanse (done)

- Removed dead LangGraph ``updates``→todos TUI path (execute does not emit it)
- Removed unused ``set_running_stage`` / ``_running_stage`` (stage omitted from title)
- Planner orphan ``*.progress`` still swallowed (no activity notes)
