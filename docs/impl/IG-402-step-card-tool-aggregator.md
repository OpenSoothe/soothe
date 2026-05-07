# IG-402: Step card aggregates main-agent tool calls (TUI)

## Goal

When the agent loop emits `AGENT_LOOP_STEP_STARTED` / `AGENT_LOOP_STEP_COMPLETED` for the main namespace (no goal-tree card), fold per-tool `ToolCallMessage` cards into the single `CognitionStepMessage` step card: header shows per-tool counts (e.g. `Grep(2), List(4)`), body lists one CLI-style row per tool call with result status. The `task` tool still mounts the existing subagent `ToolCallMessage` for internal activity; a matching row appears on the step card with the same row format.

## Decisions

- **Goal-tree mode unchanged**: If `CognitionGoalTreeMessage` is active, step lines stay in the tree; tool cards remain standalone (no aggregation).
- **Subagent namespaces unchanged**: Non-main `ns_key` tool rendering unchanged.
- **Row format**: Shared helper in `soothe_cli.tui.tool_display` reuses `format_tool_cli_style_command` + `PresentationEngine.format_tool_result_status_line`.
- **Persistence**: `MessageData.step_tool_calls_json` stores step tool rows for `STEP_PROGRESS` virtualization round-trip.

## Files

- `packages/soothe-cli/src/soothe_cli/tui/tool_display.py` — `format_tool_call_row`
- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages.py` — `CognitionStepMessage` tool rows + collapse
- `packages/soothe-cli/src/soothe_cli/tui/widgets/message_store.py` — `step_tool_calls_json`
- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` — routing, HITL, interrupt, spinner
- `docs/specs/RFC-500-cli-tui-architecture.md`, `docs/specs/RFC-501-display-verbosity.md`
- Tests under `packages/soothe-cli/tests/unit/`

## Status

Implemented in this change set.
