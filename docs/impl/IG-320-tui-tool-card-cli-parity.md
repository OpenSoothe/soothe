# IG-320: TUI tool card CLI parity and collapsed output

## Goal

Align `ToolCallMessage` with headless CLI tool lines: same command formatting as `CliRenderer.on_tool_call` / `format_tool_call_args`, and a single result line like `CliRenderer.on_tool_result` (✓/✗, summarized text, optional duration). Hide raw tool output by default; show it only when expanded (click / Ctrl+O).

## Scope

- `packages/soothe-cli/src/soothe_cli/tui/tool_display.py` — `format_tool_cli_style_command`
- `packages/soothe-cli/src/soothe_cli/shared/presentation_engine.py` — `format_tool_result_status_line`
- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages.py` — `ToolCallMessage` layout and lifecycle

## Verification

`./scripts/verify_finally.sh` (or targeted pytest for `soothe_cli` UX tests).
