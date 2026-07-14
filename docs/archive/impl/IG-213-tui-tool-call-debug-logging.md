# IG-213: TUI essential DEBUG logs for tool calls

**Status:** Completed  
**Scope:** `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` (`execute_task_textual` message stream)

## Goal

Add **basic, essential** `logger.debug` traces so `SOOTHE_LOG_LEVEL=DEBUG` (or CLI logging level DEBUG) in `~/.soothe/logs/soothe-cli.log` shows:

- Effective verbosity vs `show_tool_ui`
- Tool **results** (match card, orphan, skipped when UI off, missing `tool_call_id`)
- Tool **cards** from AI blocks (mounted, deferred streaming args, missing stable id)

## Verification

- `./scripts/verify_finally.sh`
