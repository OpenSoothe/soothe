# IG-428: Step card latest tool activity preview

## Goal

Show the latest three per-tool invocation lines on step cards: main-agent tools at the first-level branch (alongside task activity), nested task tools under each task branch, always above the Running/status line.

## Decisions

- Cap: `STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT` (3) in `preview_limits.py`.
- Format: `soothe_cli.tui.tool_display` (`DisplayName(arg)` + phase tail).
- Stats on Running lines unchanged (`Grep(N)` aggregates).
- Full nested list remains behind `STEP_CARD_SHOW_TOOL_ROW_DETAILS`.

## Files

- `packages/soothe-cli/src/soothe_cli/tui/preview_limits.py`
- `packages/soothe-cli/src/soothe_cli/tui/tool_display.py`
- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages.py`
- `packages/soothe-cli/tests/unit/ux/tui/test_tool_display.py`
- `packages/soothe-cli/tests/unit/ux/tui/test_step_card_task_activity.py`

## Status

Implemented.
