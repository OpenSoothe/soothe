# IG-344: Compact subagent TUI output (claude / browser / research)

## Status

Implemented.

## Context (IG-343)

- Headless `--no-tui` uses `HeadlessCliRenderer` + `EventProcessor(headless_output=True)`: stdout is RFC-614 loop-tagged main text only; no change in this IG.
- TUI uses `CliRenderer` + `StreamDisplayPipeline` with fixed former-`normal` semantics.

## Goal

On direct routes (`/claude`, `/browser`, `/research`, `/explore`):

- Task card shows wire milestones + completion line with a one-line **summary** (no full subagent markdown body for claude/browser/research).
- Main agent does not re-append a long duplicate answer in the same turn (`direct_subagent_turn`).

## Implementation

- **Claude**: `ClaudeStepCompletedEvent` per `ToolUseBlock`; `summary` on `ClaudeCompletedEvent` (heuristic from last text blocks).
- **Browser**: `BrowserStepCompletedEvent` promoted to NORMAL visibility in registration; `summary` on `BrowserCompletedEvent` from `final_result()` first line.
- **Research**: `ResearchGatherSummaryEvent` promoted to NORMAL; `summary` on `ResearchCompletedEvent` from synthesized answer.
- **SDK**: Allowlist + `summarize_subagent_wire_activity` for claude step.
- **CliRenderer**: Drop Task-scoped assistant chunks for `claude`/`browser`/`research` (explore keeps JSON summary path).
- **textual_adapter**: `compact_via_task` for all four; suppress main-agent text when `direct_subagent_turn`.
- **Pipeline / formatter**: Append optional `answer_summary` to `Task(...) -> ✓ Completed (Nms)` line; `_extract_result_preview` prefers event `summary`.

## Verification

`./scripts/verify_finally.sh`
