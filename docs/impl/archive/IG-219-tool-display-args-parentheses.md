# IG-219: Tool and task argument display in parentheses

**Status:** Completed  
**Scope:** Ensure tool and `task` invocations show meaningful arguments inside `()` in CLI, TUI, and Claude subagent progress events.

## Checklist

- [x] [`packages/soothe-cli/src/soothe_cli/shared/message_processing.py`](../../packages/soothe-cli/src/soothe_cli/shared/message_processing.py) — `format_tool_call_args`: unmapped tools with args; placeholder when empty; optional `task` map entry
- [x] [`packages/soothe-cli/src/soothe_cli/tui/tool_display.py`](../../packages/soothe-cli/src/soothe_cli/tui/tool_display.py) — `task` branch uses `()` and optional description
- [x] [`packages/soothe/src/soothe/subagents/claude/events.py`](../../packages/soothe/src/soothe/subagents/claude/events.py) + [`implementation.py`](../../packages/soothe/src/soothe/subagents/claude/implementation.py) — `ClaudeToolUseEvent.args_preview` + template
- [x] Tests: `test_message_processing.py`, `test_tool_display.py`, `test_claude_tool_input_preview.py`
- [x] `./scripts/verify_finally.sh` passes

## Notes

- Root cause: `_ARG_DISPLAY_MAP` miss returned `""` for any unmapped tool with non-empty args, yielding `⚙ name()` in headless CLI.
- Claude `ToolUseBlock` input is now summarized into `args_preview` for DETAILED event lines.
- **Follow-up (streaming overlay):** `build_streaming_args_overlay` used a ``tui_stream_mounted`` flag that stopped updating the overlay after the first successful JSON parse. When ``args_str`` grew on later chunks, the TUI kept stale or empty args → ``read_file(…)``. Removed the gate; overlay always reflects the latest parse. DEBUG logs: ``soothe.daemon.query_engine`` (`stream_messages_debug`), ``soothe_cli.shared.tool_call_resolution`` (`tool_stream_overlay`), ``soothe_cli.tui.textual_adapter`` (mount line with ``arg_keys``).
